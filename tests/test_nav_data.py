"""Navigation data: Kynapse path data (.hpd) and world definition (.aipathdata).

Engine evidence: CHierarchicalGraphManager 0x90b310 / 0x90b660 / 0x90b930 /
0x90d9c0 (header, cell table, path-object table, cells), CConcreteSlot 0x9172c0
(graph), CAiMesh 0x918940 (mesh), 0x91b470 (inside test), KynapseSkel
CBigFileDataReader 0x48b3c0 / 0x489e00 (definition), 0x48110f (x negation).
Everything here is synthetic and offline.
"""

import json
import math
import os
import struct
import subprocess
import sys

import numpy as np
import pytest

import nav_data as nd
from conftest import parse_glb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def _s(t):
    b = t.encode("latin-1")
    return struct.pack("<I", len(b)) + b


def _attr(k, v):
    return struct.pack("<I", 2) + _s(k) + _s(v)


def _group(name, children, label=""):
    return (
        struct.pack("<I", 0)
        + _s(label)
        + _s(name)
        + struct.pack("<I", len(children))
        + b"".join(children)
    )


def make_aipathdata(path="/data/Levels/Game_Levels_Part2/Demo/Gameplay/DemoAIPath.hpd", big=False):
    db = _group(
        "Database",
        [_attr("Path", path), _attr("ConcreteSlotSize", "121"), _attr("EndiannessSwap", "True")],
        "Characters",
    )
    gm = _group(
        "Service",
        [_attr("Class", "CHierarchicalGraphManager"), _group("Databases", [db])],
        "HierarchicalGraphManager",
    )
    pf = _group(
        "Service",
        [
            _attr("Class", "CHierarchicalPathFinder"),
            _attr("Database", "Characters"),
            _group(
                "Modifiers_IGoto",
                [
                    _group("IGoto", [_attr("Class", "CGoto_Trivial")], "trivial"),
                    _attr("default", "trivial"),
                ],
            ),
        ],
        "CharacterPathfinder",
    )
    po = _group(
        "Service",
        [
            _attr("Class", "CHierarchicalPathObjectManager"),
            _group(
                "PathObjectsPool",
                [_attr("Name", "AIStaticPathObject"), _attr("Count", "50"), _attr("Type", "1")],
            ),
        ],
        "HierarchicalPathObjectManager",
    )
    brain = _group(
        "Brain",
        [
            _attr("Class", "KynapseNPCBrain"),
            _attr("Agent", "GotoAgent"),
            _attr("Agent", "GotoAgent"),
        ],
        "NPCBrain",
    )
    root = _group(
        "Level",
        [
            _attr("OneMeter", "1.0"),
            _attr("MaxEntity", "1000"),
            _group("GlobalServices", [_attr("Service", "GapManager")]),
            _group("Brains", [brain]),
            _group("Services", [pf, po, gm]),
            struct.pack("<I", 1) + struct.pack("<I", 3) + b"\x01\x02\x03",
        ],
    )
    body = b"KS BIG FILE" + struct.pack("<I", 1) + root
    return struct.pack(">I" if big else "<I", len(body)) + body


def _vec(p):
    return struct.pack("<3f", *p)


def make_mesh(
    floors, nx=1, nz=1, version=5, sector=0x00000100, cell=20.0, x_min=-10.0, z_min=-10.0
):
    """floors: {(i, j): [floor dict]} with keys alt, links, link_to, mesh_links,
    inner, outline (list of polylines), directional."""
    b = b"Kynogon Mesh" + struct.pack("<I", version)
    if version >= 5:
        b += struct.pack("<I", sector)
    b += struct.pack("<5f", cell, x_min, x_min + cell * nx, z_min, z_min + cell * nz)
    b += struct.pack("<II", nx, nz)
    if version >= 4:
        b += struct.pack("<f", 0.25)
    if version >= 2:
        b += struct.pack("<f", -0.707106)
    if version >= 3:
        b += struct.pack("<f", 0.4)
    order = []
    for i in range(nx):
        for j in range(nz):
            fl = floors.get((i, j), [])
            b += struct.pack("<I", len(fl))
            for f in fl:
                order.append(f)
                b += struct.pack("<2f", *f["alt"])
                b += struct.pack("<I", 0)  # level links
                links = f.get("links", [])
                b += struct.pack("<I", len(links)) + b"".join(_vec(p) + _vec(q) for p, q in links)
                if version >= 5:
                    ml = f.get("mesh_links", [])
                    b += struct.pack("<I", len(ml))
                    for p, q, t in ml:
                        b += (
                            _vec(p)
                            + _vec(q)
                            + struct.pack("<4I", *t)
                            + struct.pack("<3f", 0.0, 1.0, 0.0)
                        )
                for key in ("inner", "outline"):
                    pls = f.get(key, [])
                    b += struct.pack("<I", len(pls))
                    for pl in pls:
                        b += struct.pack("<I", len(pl)) + b"".join(_vec(p) for p in pl)
                dz = f.get("directional", [])
                b += struct.pack("<I", len(dz))
                for d, pl in dz:
                    b += struct.pack("<I", len(pl)) + _vec(d) + b"".join(_vec(p) for p in pl)
                if version == 1:
                    b += struct.pack("<I", 0)
    for f in order:
        for t in f.get("link_to", []):
            b += struct.pack("<3I", *t)
    return b


def make_cell(verts, edges, mesh, vstride=36):
    """verts: [(id, border, (x, y, z))]; edges: [(a, b, path_object)] sorted by a."""
    nv = len(verts)
    first = {}
    for i, e in enumerate(edges):
        first.setdefault(e[0], i + 1)
    order = [sorted(range(nv), key=lambda k: (verts[k][2][a], k)) for a in range(3)]
    lens = [math.dist(verts[a][2], verts[b][2]) for a, b, _p in edges]
    b = struct.pack("<II", nv, len(edges))
    for i, (vid, border, p) in enumerate(verts):
        b += struct.pack(
            "<I3fIfI",
            vid | (0x80000000 if border else 0),
            p[0],
            p[1],
            p[2],
            0x80000000,
            max(lens) if (i == 0 and lens) else 0.0,
            first.get(i, 0),
        )
        b += struct.pack("<3HH", order[0][i], order[1][i], order[2][i], 0)
        b += b"\0" * (vstride - 36)
    for (a, c, po), ln in zip(edges, lens):
        b += struct.pack("<III", 0x80000000 | (po << 16) | int(ln * 16), a, c)
    b += mesh
    b += struct.pack("<II", len(mesh), 0)
    return b


def make_hpd(cells, path_objects=((1, 8, 1),), version=1.3, junk=b""):
    """cells: [(id, cell bytes, box)] -> file bytes."""
    hdr = bytearray(0x84)
    struct.pack_into("<fII", hdr, 0, version, len(cells), 1)
    struct.pack_into("<3I", hdr, 0x1C, 2, 0, 6)
    struct.pack_into("<II", hdr, 0x7C, 36, 12)
    one = abs(version - 1.0) < 1e-6
    table = b""
    data = b""
    for cid, blob, box in cells:
        e = struct.pack(
            "<I6f3I", cid, box[0], box[1], box[2], box[3], box[4], box[5], 0, len(blob), len(data)
        )
        if not one:
            e += struct.pack("<II", 90127, 11483800)
        table += e
        data += blob + junk
    po = b""
    if version >= 1.2999:
        po = struct.pack("<fI", 1.0, len(path_objects))
        for pid, flags, typ in path_objects:
            po += struct.pack("<IHH", pid, flags, typ)
    return bytes(hdr) + table + po + data


# a 6 x 4 m room (file x 0..6, z 0..4) with a 2 x 1 m pillar hole and a portal
SQUARE = [
    [(0.0, 1.0, 0.0), (6.0, 1.0, 0.0)],
    [(6.0, 1.0, 0.0), (6.0, 1.0, 4.0)],
    [(6.0, 1.0, 4.0), (0.0, 1.0, 4.0)],
    # the west side is a link (portal), added below
    [(2.0, 1.0, 1.0), (4.0, 1.0, 1.0)],
    [(4.0, 1.0, 1.0), (4.0, 1.0, 2.0)],
    [(4.0, 1.0, 2.0), (2.0, 1.0, 2.0)],
    [(2.0, 1.0, 2.0), (2.0, 1.0, 1.0)],
]


def demo_floor():
    return {
        "alt": (0.0, 1.6),
        "outline": SQUARE,
        "links": [((0.0, 1.0, 4.0), (0.0, 1.0, 0.0))],
        "link_to": [(0, 0, 1)],
        "mesh_links": [((6.0, 1.0, 0.0), (6.0, 1.0, 0.0), (0xFFFFFFFF, 0, 0, 0))],
        "inner": [[(1.0, 1.0, 3.0), (1.5, 1.0, 3.0)]],
        "directional": [
            ((1.0, 0.0, 0.0), [(5.0, 1.0, 3.0), (5.5, 1.0, 3.0), (5.5, 1.0, 3.5), (5.0, 1.0, 3.0)])
        ],
    }


def demo_hpd(**kw):
    f2 = {
        "alt": (4.0, 5.6),
        "outline": [
            [(0.0, 5.0, 0.0), (1.0, 5.0, 0.0)],
            [(1.0, 5.0, 0.0), (0.0, 5.0, 1.0)],
            [(0.0, 5.0, 1.0), (0.0, 5.0, 0.0)],
        ],
    }
    mesh = make_mesh({(0, 0): [demo_floor(), f2]})
    v1 = [
        (101, False, (1.0, 1.0, 0.5)),
        (102, False, (5.0, 1.0, 0.5)),
        (103, True, (5.0, 1.0, 3.5)),
    ]
    e1 = [(0, 1, 0), (1, 0, 0), (1, 2, 1), (2, 1, 1)]
    v2 = [
        (103, True, (5.0, 1.0, 3.5)),
        (104, False, (9.0, 2.0, 3.5)),
        (105, False, (30.0, 1.0, 30.0)),
    ]
    e2 = [(0, 1, 0)]
    c1 = make_cell(v1, e1, mesh)
    c2 = make_cell(v2, e2, make_mesh({}, sector=0x00000200))
    return make_hpd(
        [(1000, c1, (1.0, 5.0, 1.0, 1.0, 0.5, 3.5)), (1001, c2, (5.0, 30.0, 1.0, 2.0, 3.5, 30.0))],
        **kw,
    )


# ---------------------------------------------------------------------------
# .aipathdata
# ---------------------------------------------------------------------------


def test_aipathdata_tree_and_summary():
    t = nd.parse_aipathdata(make_aipathdata())
    assert t["version"] == 1 and t["trailing"] == 0 and t["size_field_endian"] == "little"
    root = t["root"]
    assert root["name"] == "Level" and root["label"] == ""
    assert nd.tree_attr(root, "MaxEntity") == "1000"
    assert root["children"][-1] == {"raw": "010203"}  # kind 1 node
    s = nd.config_summary(t)
    assert s["level"] == {"OneMeter": 1.0, "MaxEntity": 1000}
    assert s["global_services"] == ["GapManager"]
    # duplicates are data: the brain lists the goto agent twice
    assert s["brains"] == [
        {
            "name": "NPCBrain",
            "class": "KynapseNPCBrain",
            "services": [],
            "agents": ["GotoAgent"] * 2,
        }
    ]
    assert s["path_object_pools"] == [{"Name": "AIStaticPathObject", "Count": 50, "Type": 1}]
    assert (
        s["databases"][0]["name"] == "Characters" and s["databases"][0]["ConcreteSlotSize"] == 121
    )
    assert s["path_finders"][0]["modifiers"]["IGoto"] == {
        "default": "trivial",
        "items": [{"name": "trivial", "Class": "CGoto_Trivial"}],
    }
    assert nd.database_path(t).endswith("/Demo/Gameplay/DemoAIPath.hpd")


def test_aipathdata_console_size_field_is_big_endian():
    t = nd.parse_aipathdata(make_aipathdata(big=True))
    assert t["size_field_endian"] == "big" and t["size_field"] == t["bytes"] - 4
    assert t["root"] == nd.parse_aipathdata(make_aipathdata())["root"]


@pytest.mark.parametrize("bad", [b"", b"\0" * 40, make_aipathdata()[:60]])
def test_aipathdata_rejects_garbage(bad):
    with pytest.raises(nd.NavError):
        nd.parse_aipathdata(bad)


def test_aipathdata_version_must_be_one():
    d = bytearray(make_aipathdata())
    struct.pack_into("<I", d, 15, 2)
    with pytest.raises(nd.NavError):
        nd.parse_aipathdata(bytes(d))


# ---------------------------------------------------------------------------
# .hpd
# ---------------------------------------------------------------------------


def test_hpd_header_cells_and_graph():
    data = demo_hpd()
    h = nd.parse_hpd(data)
    assert abs(h["header"]["version"] - 1.3) < 1e-6
    assert h["header"]["cell_mode"] == 1
    assert (h["header"]["vertex_stride"], h["header"]["edge_stride"]) == (36, 12)
    assert h["header"]["vertex_attributes"][0] == (2, 0, 6)
    assert h["path_objects"] == [{"index": 1, "id": 1, "flags": 8, "pool_type": 1}]
    assert h["undecoded"] == []
    assert sum(s for _w, _o, s in h["regions"]) == len(data) == h["bytes"]
    c = h["cells"][0]
    assert c["id"] == 1000 and c["level"] == 0 and c["date"] == 90127
    assert c["box"] == (1.0, 5.0, 1.0, 1.0, 0.5, 3.5)
    v = c["vertices"]
    assert [x["id"] for x in v] == [101, 102, 103]
    assert [x["border"] for x in v] == [False, False, True]
    assert v[1]["pos"] == (5.0, 1.0, 0.5)  # file space, untouched
    assert [x["first_edge"] for x in v] == [0, 1, 3]
    assert all(x["abstract"] is None for x in v)
    assert c["max_edge_length"] == pytest.approx(4.0)
    assert c["sorted"][0] == [0, 1, 2] and c["sorted"][2] == [0, 1, 2]
    e = c["edges"]
    assert [(x["from"], x["to"], x["path_object"]) for x in e] == [
        (0, 1, 0),
        (1, 0, 0),
        (1, 2, 1),
        (2, 1, 1),
    ]
    assert e[0]["length_q"] == 64 and e[2]["length_q"] == 48 and all(x["unbound"] for x in e)
    assert h["cells"][1]["vertices"][1]["first_edge"] is None  # no edge leaves it


def test_hpd_mesh_fields():
    m = nd.parse_hpd(demo_hpd())["cells"][0]["mesh"]
    assert m["version"] == 5 and m["sector_word"] == 0x100
    assert (m["cell_size"], m["x_min"], m["x_max"], m["z_min"], m["z_max"]) == (
        20.0,
        -10.0,
        10.0,
        -10.0,
        10.0,
    )
    assert (m["nx"], m["nz"], m["margin"]) == (1, 1, 0.25)
    assert m["radius"] == pytest.approx(0.4)
    assert len(m["floors"]) == 2
    f = m["floors"][0]
    assert (f["alt_min"], f["alt_max"]) == (0.0, pytest.approx(1.6))
    assert len(f["outline"]) == 7 and len(f["links"]) == 1 and f["link_targets"] == [(0, 0, 1)]
    assert f["mesh_links"][0][2] == (0xFFFFFFFF, 0, 0, 0)
    assert f["inner_walls"] == [[(1.0, 1.0, 3.0), (1.5, 1.0, 3.0)]]
    assert f["directional"][0][0] == (1.0, 0.0, 0.0) and len(f["directional"][0][1]) == 4
    assert m["floors"][1]["index"] == 1 and m["floors"][1]["cell"] == (0, 0)


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
def test_mesh_versions_read_what_the_loader_reads(version):
    # 0x918940: +4 only in v5, margin from v4, +0x34 from v3, +0x30 from v2,
    # mesh links only in v5, one dropped word per floor in v1
    fl = {"alt": (0.0, 1.0), "outline": [[(0.0, 0.5, 0.0), (1.0, 0.5, 0.0)]]}
    blob = make_mesh({(0, 0): [fl]}, version=version)
    cell = make_cell([(1, False, (0.0, 0.0, 0.0))], [], blob)
    h = nd.parse_hpd(make_hpd([(7, cell, (0, 0, 0, 0, 0, 0))]))
    m = h["cells"][0]["mesh"]
    assert h["undecoded"] == [] and m["version"] == version
    assert m["margin"] == (0.25 if version >= 4 else 0.0)
    assert m["radius"] == (pytest.approx(0.4) if version >= 3 else 0.0)
    assert m["floors"][0]["outline"] == [[(0.0, 0.5, 0.0), (1.0, 0.5, 0.0)]]


def test_hpd_version_1_0_has_short_cell_entries_and_no_path_object_table():
    # 0x90b310: 0x28-byte entries for version 1.0; 0x90b660: table only from 1.3
    cell = make_cell([(1, False, (0.0, 0.0, 0.0))], [], make_mesh({}))
    h = nd.parse_hpd(make_hpd([(7, cell, (0, 0, 0, 0, 0, 0))], version=1.0))
    assert h["path_objects"] == [] and h["data_offset"] == 0x84 + 0x28
    assert "date" not in h["cells"][0] and h["undecoded"] == []


def test_hpd_reports_bytes_it_does_not_understand():
    data = demo_hpd() + b"\xaa" * 5
    h = nd.parse_hpd(data)
    assert h["undecoded"] == [{"what": "after the last cell", "offset": len(data) - 5, "size": 5}]
    doc = nd.build_document(h)
    assert doc["coverage"]["undecoded_bytes"] == 5 and doc["coverage"]["bytes"] == len(data)


def test_hpd_abstract_cell_is_reported_not_guessed():
    data = bytearray(demo_hpd())
    struct.pack_into("<I", data, 0x84 + 0x30 + 0x1C, 1)  # second cell: hierarchy level 1
    h = nd.parse_hpd(bytes(data))
    assert h["cells"][1]["vertices"] == []
    assert [u["what"] for u in h["undecoded"]] == ["abstract cell 1001"]


@pytest.mark.parametrize("cut", [10, 0x84, 0x90, 0xF0, 300, -9, -1])
def test_hpd_truncated_raises(cut):
    data = demo_hpd()
    with pytest.raises(nd.NavError):
        nd.parse_hpd(data[:cut])


def test_hpd_rejects_other_files():
    with pytest.raises(nd.NavError):
        nd.parse_hpd(b"RIFF" + b"\0" * 400)
    bad = bytearray(demo_hpd())
    bad[bad.index(b"Kynogon Mesh")] = 0x58
    with pytest.raises(nd.NavError):
        nd.parse_hpd(bytes(bad))


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------


def test_triangulation_is_the_even_odd_region():
    fl = nd.parse_hpd(demo_hpd())["cells"][0]["mesh"]["floors"][0]
    segs = [(a, b) for a, b, _k in nd.floor_segments(fl)]
    assert len(segs) == 9  # 7 outline, 1 link, 1 mesh link; the inner wall is not a bound
    pts, tris, opn = nd.triangulate(segs)
    assert opn == 0
    area = sum(nd._tri_area(pts, t) for t in tris)
    assert area == pytest.approx(6 * 4 - 2 * 1)  # room minus pillar
    for t in tris:  # wound with the normal up
        a, b, c = (pts[i] for i in t)
        assert (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]) > 0
    assert nd.point_in_floor(fl, (1.0, 1.0, 1.5))
    assert not nd.point_in_floor(fl, (3.0, 1.0, 1.5))  # inside the pillar
    assert not nd.point_in_floor(fl, (1.0, 2.0, 1.5))  # above the floor's altitude range
    assert not nd.point_in_floor(fl, (7.0, 1.0, 1.5))


def test_triangulation_reports_an_open_outline():
    segs = [
        ((0, 0, 0), (2, 0, 0)),
        ((2, 0, 0), (2, 0, 2)),
        ((2, 0, 2), (0, 0, 2)),
    ]  # west side missing
    _p, tris, opn = nd.triangulate(segs)
    assert opn == 1 and tris == []


def test_locate():
    h = nd.parse_hpd(demo_hpd())
    r = nd.locate(h, (1.0, 0.0, 1.5))  # a metre below the outline: placement pivots are
    assert r["on_mesh"] and r["floor"] == [0, 0, 0] and r["cell"] == 1000
    r = nd.locate(h, (-1.0, 0.0, 2.0))
    assert not r["on_mesh"] and r["distance"] == pytest.approx(1.0)
    assert nd.locate(h, (1.0, 50.0, 1.5))["distance"] is None


def test_graph_summary_joins_cells_by_vertex_id():
    g = nd.graph_summary(nd.parse_hpd(demo_hpd()))
    assert g["vertex_records"] == 6 and g["nodes"] == 5  # id 103 is in both cells
    assert g["edges"] == 5 and g["path_object_edges"] == 2
    assert g["components"] == 2 and g["component_sizes"] == [4, 1]
    assert g["one_way_edges"] == 1
    assert g["stored_length_max_error"] <= 1 / 32 + 1e-6


# ---------------------------------------------------------------------------
# document and GLB (engine space)
# ---------------------------------------------------------------------------


def test_document_is_in_engine_space():
    h = nd.parse_hpd(demo_hpd())
    doc = nd.build_document(h, nd.parse_aipathdata(make_aipathdata()), "Demo", {"hpd": "demo.hpd"})
    assert doc["format"] == "watchmen-nav/1" and doc["level"] == "Demo"
    assert doc["conventions"]["x_negated_from_file"] is True
    c = doc["cells"][0]
    assert c["vertices"][1]["pos"] == [-5.0, 1.0, 0.5]  # x negated (0x48110f)
    assert c["box_min"] == [-5.0, 1.0, 0.5] and c["box_max"] == [-1.0, 1.0, 3.5]
    assert c["generated"] == "2009-01-27 11:48:38"
    assert c["edges"][0] == {
        "from": 0,
        "to": 1,
        "length": 4.0,
        "path_object": None,
        "unbound": True,
    }
    assert c["edges"][2]["path_object"] == 1
    m = c["mesh"]
    assert m["sector"] == {"word": 256, "x": 0, "z": 1}
    assert m["bounds_min"] == [-10.0, -10.0] and m["bounds_max"] == [10.0, 10.0]
    f = m["floors"][0]
    assert f["area"] == pytest.approx(22.0) and f["triangles"] > 0
    assert f["outline"][0] == [[0.0, 1.0, 0.0], [-6.0, 1.0, 0.0]]
    assert f["links"] == [{"a": [0.0, 1.0, 4.0], "b": [0.0, 1.0, 0.0], "to": [0, 0, 1]}]
    assert f["mesh_links"][0]["to_sector"] is None
    assert f["directional"][0]["dir"] == [-1.0, 0.0, 0.0]
    assert "open_outline" not in f
    po = doc["path_objects"]
    assert len(po) == 1 and len(po[0]["edges"]) == 2
    assert po[0]["edges"][0] == {
        "cell": 1000,
        "edge": 2,
        "from": [-5.0, 1.0, 0.5],
        "to": [-5.0, 1.0, 3.5],
    }
    s = doc["summary"]
    assert s["cells"] == 2 and s["mesh"]["floors"] == 2 and s["mesh"]["inner_walls"] == 1
    assert s["mesh"]["area"] == pytest.approx(22.5)
    assert doc["config"]["databases"][0]["name"] == "Characters"
    assert doc["config_tree"]["name"] == "Level"
    assert doc["coverage"]["undecoded_bytes"] == 0
    # the writer keeps records on one line and the result is plain JSON
    text = nd.dumps(doc)
    assert json.loads(text) == json.loads(json.dumps(doc))
    assert '"pos": [-5.0, 1.0, 0.5]' in text


@pytest.mark.usefixtures("engine_frame")  # pins the engine numbers; true frame: test_frame.py
def test_glb_structure_and_space():
    h = nd.parse_hpd(demo_hpd())
    g = parse_glb_bytes(nd.build_glb(h, "Demo"))
    names = [n["name"] for n in g.j["nodes"]]
    assert names[-1] == "nav Demo"
    for want in (
        "navmesh",
        "navmesh_walls",
        "navmesh_links",
        "navmesh_inner_walls",
        "graph_edges",
        "graph_path_object_edges",
        "graph_vertices",
    ):
        assert want in names
    assert g.j["extras"]["format"] == "watchmen-nav/1"
    by = dict(
        (n["name"], g.j["meshes"][n["mesh"]]["primitives"][0]) for n in g.j["nodes"] if "mesh" in n
    )
    assert (
        by["navmesh"]["mode"] == 4
        and by["graph_edges"]["mode"] == 1
        and by["graph_vertices"]["mode"] == 0
    )
    p = g.accessor(by["navmesh"]["attributes"]["POSITION"])
    i = g.accessor(by["navmesh"]["indices"]).reshape(-1, 3)
    assert p[:, 0].min() == -6.0 and p[:, 0].max() == 0.0  # engine x = -file x
    a, b, c = p[i[:, 0]], p[i[:, 1]], p[i[:, 2]]
    ny = (b[:, 2] - a[:, 2]) * (c[:, 0] - a[:, 0]) - (b[:, 0] - a[:, 0]) * (c[:, 2] - a[:, 2])
    assert (ny > 0).all() and 0.5 * ny.sum() == pytest.approx(22.5)
    gv = g.accessor(by["graph_vertices"]["attributes"]["POSITION"])
    assert len(gv) == 6 and [-5.0, 1.0, 0.5] in gv.tolist()
    ge = g.accessor(by["graph_edges"]["indices"])
    assert len(ge) == 2 * 2  # 0<->1 drawn once, the one-way edge of cell 2 once
    assert len(g.accessor(by["graph_path_object_edges"]["indices"])) == 2
    acc = g.j["accessors"][by["navmesh"]["attributes"]["POSITION"]]
    assert acc["min"] == [float(x) for x in p.min(axis=0)]
    assert g.total_length == len(g.raw) and len(g.bin_chunk) % 4 == 0


def parse_glb_bytes(raw, _tmp=[0]):
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as fh:
        fh.write(raw)
        name = fh.name
    try:
        return parse_glb(name)
    finally:
        os.unlink(name)


# ---------------------------------------------------------------------------
# files and CLI
# ---------------------------------------------------------------------------


def _tree(tmp_path):
    a = tmp_path / "ex" / "extracted" / "Levels" / "Game_Levels_Part2" / "Demo" / "Gameplay"
    f = tmp_path / "ex" / "files" / "data" / "levels" / "game_levels_part2" / "demo" / "gameplay"
    o = tmp_path / "ex" / "files" / "data" / "levels" / "game_levels_part2" / "other" / "gameplay"
    for d in (a, f, o):
        d.mkdir(parents=True)
    (a / "DemoAIPath.aipathdata").write_bytes(make_aipathdata())
    (f / "demoaipath.hpd").write_bytes(demo_hpd())
    (o / "other.hpd").write_bytes(demo_hpd())
    return tmp_path / "ex"


def test_find_inputs_pairs_definition_and_path_data(tmp_path):
    root = _tree(tmp_path)
    got = nd.find_inputs(str(root))
    assert [e["level"] for e in got] == ["Demo", "other"]
    assert got[0]["hpd"].endswith("demoaipath.hpd") and got[0]["aipathdata"].endswith(
        "DemoAIPath.aipathdata"
    )
    assert got[1]["aipathdata"] is None
    one = nd.find_inputs(got[1]["hpd"])
    assert one == [{"level": "other", "hpd": got[1]["hpd"], "aipathdata": None}]


def test_cli_navmeta(tmp_path):
    root = _tree(tmp_path)
    out = tmp_path / "nav"
    r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "watchmen.py"), "navmeta", str(root), str(out)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "wrote 2 level(s)" in r.stdout and "0 undecoded bytes" in r.stdout
    assert sorted(os.listdir(str(out))) == [
        "Demo.nav.glb",
        "Demo.nav.json",
        "other.nav.glb",
        "other.nav.json",
    ]
    doc = json.loads((out / "Demo.nav.json").read_text(encoding="utf-8"))
    assert doc["format"] == "watchmen-nav/1" and doc["source"] == {
        "hpd": "demoaipath.hpd",
        "aipathdata": "DemoAIPath.aipathdata",
    }
    assert "config" in doc and "config" not in json.loads(
        (out / "other.nav.json").read_text(encoding="utf-8")
    )
    assert parse_glb(str(out / "Demo.nav.glb")).j["nodes"][-1]["name"] == "nav Demo"
    # deterministic
    first = (out / "Demo.nav.json").read_bytes(), (out / "Demo.nav.glb").read_bytes()
    subprocess.run(
        [sys.executable, os.path.join(ROOT, "watchmen.py"), "navmeta", str(root), str(out)],
        capture_output=True,
        check=True,
    )
    assert first == ((out / "Demo.nav.json").read_bytes(), (out / "Demo.nav.glb").read_bytes())


def test_cli_navmeta_errors(tmp_path):
    exe = [sys.executable, os.path.join(ROOT, "watchmen.py"), "navmeta"]
    r = subprocess.run(
        exe + [str(tmp_path / "nope"), str(tmp_path / "o")], capture_output=True, text=True
    )
    assert r.returncode == 2 and "does not exist" in r.stderr
    (tmp_path / "empty").mkdir()
    r = subprocess.run(
        exe + [str(tmp_path / "empty"), str(tmp_path / "o")], capture_output=True, text=True
    )
    assert r.returncode == 1 and "no .hpd" in r.stderr
    bad = tmp_path / "bad" / "x" / "gameplay"
    bad.mkdir(parents=True)
    (bad / "x.hpd").write_bytes(demo_hpd()[:200])
    r = subprocess.run(
        exe + [str(tmp_path / "bad"), str(tmp_path / "o")], capture_output=True, text=True
    )
    assert r.returncode == 1 and "ERROR" in r.stdout and "1 failed" in r.stdout


def test_definition_without_path_data_still_exports(tmp_path):
    p = tmp_path / "Lone" / "Gameplay"
    p.mkdir(parents=True)
    (p / "Lone.aipathdata").write_bytes(make_aipathdata(path="/data/x/Lone/Gameplay/Lone.hpd"))
    res = nd.export(str(tmp_path), str(tmp_path / "o"))
    assert len(res) == 1 and res[0]["level"] == "Lone" and "glb" not in res[0]
    doc = json.loads((tmp_path / "o" / "Lone.nav.json").read_text(encoding="utf-8"))
    assert doc["config"]["databases"][0]["Path"].endswith("Lone.hpd") and "cells" not in doc


def test_float_text_is_the_shortest_float32():
    assert nd._f(np.float32(59.31005)) == 59.31005 and nd._f(0.1) == 0.1
    assert (
        nd._ev((0.0, 1.0, 2.0)) == [0.0, 1.0, 2.0]
        and math.copysign(1, nd._ev((0.0, 1, 2))[0]) == 1.0
    )
