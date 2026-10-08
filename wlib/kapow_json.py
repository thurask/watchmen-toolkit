#!/usr/bin/env python3
# Human-readable JSON emitters for Kapow property/sequence/fragment assets.
# Used by watchmen_extract.py (extracted/*.json) and standalone:
#   python3 kapow_json.py FILE            (prints JSON)
import json, struct, re, math, bisect
import kapow_props, decode_sequence

# a .scene is a fragment whose root is the SceneNode (engine: same Fragment asset type)
FRAGMENT_EXTS = (".fragment", ".scene")
PROPBAG_EXTS = (".particle", ".grass", ".detailmesh", ".pb", ".terrain")
POSK = 0x2F0823C4
ROTK = 0x51172879

NAMEK = 0x7282B2A2  # kapow keyHash of NAME (stored in platform byte order)


_NOT_PRINTABLE = bytes(0 if 32 <= c < 127 else 1 for c in range(256))


def _read_bytes(path):
    """The file's bytes; the handle is closed before returning."""
    with open(path, "rb") as fh:
        return fh.read()


def _schema_name(d, p, e):
    """The first candidate type name among the strings d[s:e], s = p .. e - 1 (d[e] is
    the NUL that ends the run): the longest all-printable tail of the run when it
    ends with ")", else that tail from its first "{" on; at least 3 bytes.  None when
    no start offset qualifies."""
    run = d[p:e]
    s = p + run.translate(_NOT_PRINTABLE).rfind(b"\x01") + 1  # first start with a printable tail
    if e - s < 3:
        return None
    if d[e - 1] != 0x29:  # ")"
        s = d.find(b"{", s, e - 2)
        if s < 0:
            return None
    return d[s:e]


def fragment_json(d, bo="<"):
    # 1) node-type tree (schema table)
    # A type name is a printable string of 3+ bytes that ends with ")" or starts with
    # "{", closed by a NUL and followed (after up to 8 more NULs) by a 12-byte record
    # that looks like a node header.  The scan tries every start offset in turn; all
    # starts inside one NUL-free run share that run's end and so its record, which is
    # why the run is judged once (_schema_name) instead of once per start offset: the
    # per-offset form re-read the rest of the run each time, quadratic in its length.
    nodes = []
    p = 0
    n = len(d)
    while p < n:
        e = d.find(b"\x00", p)
        if e < 0:
            break
        s = _schema_name(d, p, e)
        if s is not None:
            q = e + 1
            while q < n and d[q] == 0 and q - (e + 1) < 8:
                q += 1
            if q + 12 <= n:
                mark, h, depth = struct.unpack_from(bo + "III", d, q)
                if depth < 40 and (mark >= 0xFFFFFFF0 or 0x10000 < mark < 0xFFFFFF00):
                    nodes.append({"depth": depth, "type": s.decode("latin1"), "hash": "%08x" % h})
                    p = q + 12
                    continue
        p = e + 1  # no start offset of this run gives a node

    # 2) named instances + transforms (instance stream)
    def f(o):
        return struct.unpack_from(bo + "f", d, o)[0]

    def u(o):
        return struct.unpack_from(bo + "I", d, o)[0]

    heads = []
    for m in re.finditer(re.escape(struct.pack(bo + "I", NAMEK)), d):
        o = m.start()
        if o < 12:
            continue
        wc = u(o + 4)
        if 1 <= wc <= 30:
            nm = d[o + 8 : o + 8 + wc * 4].split(b"\x00")[0].decode("latin1", "replace")
            heads.append((o - 8, nm))
    heads.sort()
    starts = [h[0] for h in heads]

    def owner(off):
        i = bisect.bisect_right(starts, off) - 1
        return heads[i][1] if i >= 0 else None

    tr = []
    for m in re.finditer(re.escape(struct.pack(bo + "I", POSK)), d):
        o = m.start() + 4
        x, y, z = f(o), f(o + 4), f(o + 8)
        if not all(math.isfinite(v) and abs(v) < 5000 for v in (x, y, z)):
            continue
        rec = {"name": owner(m.start()), "pos": [round(x, 3), round(y, 3), round(z, 3)]}
        if o + 16 <= len(d) and u(o + 12) == ROTK:
            qq = [f(o + 16), f(o + 20), f(o + 24), f(o + 28)]
            if 0.98 < sum(c * c for c in qq) < 1.02:
                rec["quat"] = [round(c, 4) for c in qq]
                rec["yaw_deg"] = round(math.degrees(2 * math.atan2(qq[1], qq[3])), 1)
        tr.append(rec)
    # 3) ALL string properties ([u32 keyHash][u32 wordcount][wc*4 chars]) -> resource refs etc.
    keynames = kapow_props.namedict()
    strs = []
    p2 = 0
    while p2 + 12 <= len(d):
        wc = u(p2 + 4)
        if 1 <= wc <= 200 and p2 + 8 + wc * 4 <= len(d):
            raw = d[p2 + 8 : p2 + 8 + wc * 4]
            txt = raw.split(b"\x00")[0]
            # must fill most of the field and be printable
            if (
                len(txt) >= 3
                and len(txt) >= (wc - 1) * 4 - 3
                and all(32 <= c < 127 for c in txt)
                and raw[len(txt) :].strip(b"\x00") == b""
            ):
                key = u(p2)
                kn = keynames.get(key)
                if kn is None:
                    t = txt.decode("latin1").lower()
                    if t.endswith(".model"):
                        kn = "model_ref"
                    elif t.endswith(".bmp") or t.endswith(".tga"):
                        kn = "texture_ref"
                    elif ".bmp," in t or ".tga," in t:
                        kn = "texture_table"
                    elif t.endswith(".fragment"):
                        kn = "fragment_ref"
                    elif t.endswith((".wav", ".ogg")):
                        kn = "sound_ref"
                    elif t.endswith((".tnt", ".script")):
                        kn = "script_ref"
                    elif t.endswith((".animation", ".animationgraph")):
                        kn = "animation_ref"
                    elif t.endswith((".particle", ".sequence", ".pb")):
                        kn = "asset_ref"
                    else:
                        kn = "str_%08x" % key
                strs.append((p2, kn, txt.decode("latin1")))
                p2 += 8 + wc * 4
                continue
        p2 += 1
    # robust resource-ref sweep (regex, immune to stream-walk desync)
    seen_off = {st[0] for st in strs}
    for m in re.finditer(
        rb"/[ -~]{4,150}?\.(?:model|bmp|tga|fragment|wav|ogg|tnt|script|animation|animationgraph|sequence|particle|pb|terrain|grass|detailmesh)\x00",
        d,
        re.I,
    ):
        off = m.start()
        # avoid duplicating records the walk already captured (same string start)
        if any(abs(off - (so + 8)) < 3 for so in seen_off):
            continue
        txt = m.group()[:-1].decode("latin1")
        t = txt.lower()
        if t.endswith(".model"):
            kn = "model_ref"
        elif t.endswith((".bmp", ".tga")):
            kn = "texture_ref"
        elif t.endswith(".fragment"):
            kn = "fragment_ref"
        elif t.endswith((".wav", ".ogg")):
            kn = "sound_ref"
        elif t.endswith((".tnt", ".script")):
            kn = "script_ref"
        elif t.endswith((".animation", ".animationgraph")):
            kn = "animation_ref"
        else:
            kn = "asset_ref"
        strs.append((off, kn, txt))
    # dedupe (offset,value)
    strs = sorted({(o, k, v) for o, k, v in strs})
    # group per owning named instance
    inst = {}
    order = []
    for off, keyn, val in strs:
        own = owner(off) or "(preamble)"
        if own not in inst:
            inst[own] = {}
            order.append(own)
        if keyn == "name" and val == own:
            continue
        lst = inst[own].setdefault(keyn, [])
        if val not in lst:
            lst.append(val)
    for rec in tr:
        own = rec.get("name") or "(preamble)"
        if own not in inst:
            inst[own] = {}
            order.append(own)
        inst[own].setdefault("_transforms", []).append(
            {k: v for k, v in rec.items() if k != "name"}
        )
    instances = [{"name": k, **inst[k]} for k in order]
    return {
        "nodes": nodes,
        "named_instances": [n for _, n in heads],
        "instances": instances,
        "transforms": tr,
    }


def terrain_json(b, bo=None, stream=None):
    """`.terrain` header -> JSON (terrain_asset, format kapow-terrain/2): the whole
    file from the engine's loader 0x5397d0, `tail_bytes` 0.  Before 1.4.0 this read the
    three path lists and left the rest as `tail_bytes` (74 to 95% of each file).  A
    file the grammar does not fit comes back as a marked stub (`not_decoded`)."""
    import terrain_asset

    return terrain_asset.strip(terrain_asset.to_json(b, bo, stream))


#: SceneScope / SceneNode properties that are common to every node and say nothing
#: about the scene list (left out of the `scene` summary; all are in `nodes_full`)
_SCENE_COMMON = frozenset(
    (
        "UseRealTime recordInSavepoints runScript Open enabled Visible runFrameUpdate "
        "smartSelectable logicalParent siblingOrder parentLink spatialTreeStrategy localPos "
        "localOrient Locked UserType includeInAO includeInReflections castShadow "
        # the same five as the executable registers them (key table from 1.4.0 on)
        "useRealtime open visible locked userType"
    ).split()
)


def scene_summary(out):
    """The `scene` section of a `.scene` JSON: what the project scene holds, from the
    exact fragment parse (`nodes_full`).  A `.scene` is a Fragment asset (the type
    `fragment` is registered with the source extensions `scene` and `fragment`,
    0x542c1a, and has one header reader, 0x54306d); its root is the SceneNode, and the
    game's levels are its `SceneScope(LoadBlock)` nodes.
      root          the SceneNode's own properties
      scopes        one entry per SceneScope node, in file order: {id, type, name,
                    asset (assetName = the level fragment), parent (id or etag), props
                    (its other properties)}
      memory_setups in `root` and in each scope: the LoadBlockMemorySetup node behind
                    every property that refers to one ({property: {its settings}})
      other_nodes   {type: count} of the remaining node types"""
    nodes = [n for n in out.get("nodes_full") or [] if n.get("props")]
    table = {n["id"]: n for n in nodes}
    setup_common = _SCENE_COMMON | {"name"}

    def split(props):
        own, setups = {}, {}
        for k, v in props.items():
            if k in _SCENE_COMMON or k in ("name", "assetName"):
                continue
            ref = table.get(v.get("ref")) if isinstance(v, dict) else None
            if ref is not None and ref.get("type") == "LoadBlockMemorySetup":
                setups[k] = {p[0]: p[2] for p in ref["props"] if p[0] not in setup_common}
            own[k] = v
        return own, setups

    root = None
    scopes = []
    other = {}
    for n in nodes:
        t = n.get("type") or ""
        props = {p[0]: p[2] for p in n["props"]}
        if t == "SceneNode" and root is None:
            own, setups = split(props)
            root = dict(own, memory_setups=setups)
        elif t.startswith("SceneScope"):
            own, setups = split(props)
            scopes.append(
                {
                    "id": n["id"],
                    "type": t,
                    "name": props.get("name"),
                    "asset": props.get("assetName"),
                    "parent": props.get("logicalParent"),
                    "props": own,
                    "memory_setups": setups,
                }
            )
        elif t != "LoadBlockMemorySetup":
            other[t] = other.get(t, 0) + 1
    return {"root": root, "scopes": scopes, "other_nodes": other}


def detailmesh_json(data, order=None, stream=None):
    """`.detailmesh` -> the property bag (kapow_props) plus `mesh`: the bytes after
    the bag are `[u8 has_mesh]` and the vertex / index buffer descriptors (reader
    0x52de50; no flag byte in the standalone Part 1 layout).  `trailing_bytes` is what
    is still not decoded after that (0 for every file of the six tested sets).
    `inferred` (the vertex stride, which is derived from the stream size) says what is
    not read; `not_established` is empty (terrain_asset.DETAIL_NOT_ESTABLISHED)."""
    import terrain_asset

    out = kapow_props.parse(data, order=order)
    n = out.get("trailing_bytes") or 0
    if n:
        bo = order or kapow_props.detect_order(data)
        mesh, left = terrain_asset.detail_tail(data[len(data) - n :], bo)
        if mesh is not None:
            out["mesh"] = mesh
            out["trailing_bytes"] = left
            if stream:
                out["stream"] = terrain_asset.detail_stream_layout(mesh, stream, bo)
            if mesh.get("has_mesh"):
                # like the terrain and font JSON: what is derived and what has no meaning yet
                if "vertex_stride" in (out.get("stream") or {}):
                    out["inferred"] = dict(terrain_asset.DETAIL_INFERRED)
                out["not_established"] = list(terrain_asset.DETAIL_NOT_ESTABLISHED)
        else:
            out.setdefault("warn", []).append(
                "%d bytes after the property bag are not a detail mesh tail: not decoded" % n
            )
    return out


def to_json(name_lower, data, order=None, stream=None):
    """Return (json_dict or None) for a raw asset payload.
    order: '<' (PC) / '>' (X360/PS3) / None = auto-detect per asset.
    stream: the asset's stream bytes, used by `.terrain` and `.detailmesh` (their
    `stream` section); images and meshes are written by `export`."""
    if name_lower.endswith(FRAGMENT_EXTS):
        import sys as _sys

        _sys.setrecursionlimit(max(_sys.getrecursionlimit(), 8000))
        import kapow_fragment as _kf

        bo = order or _kf.detect_order(data)
        out = fragment_json(data, bo)
        try:
            r = _kf.parse(data, order=bo)
            sch = {h: t for h, t in r["schema"]}
            out["schema"] = [{"id": h, "type": t} for h, t in r["schema"]]
            out["nodes_full"] = [
                {
                    "id": i["node"],
                    "type": sch.get(i["node"]),
                    "created": bool(i.get("created")),
                    "props": [[nm, t, v] for nm, t, v in i["props"]],
                }
                for i in r["inst"]
            ]
            out["lossless"] = bool(r["ok"])
            # nodes / named_instances / instances / transforms from the exact parse (the
            # byte sweep above read integers as text); the sweep stays only as the
            # marked fallback of a fragment that does not parse to its end
            out["instances_source"] = "exact" if r["ok"] else "sweep"
            if r["ok"]:
                out.update(_kf.sections(data, r))
            if r["unknown"]:
                out["unknown_keys"] = _kf.unknown_keys(r)
            _inf = _kf.inferred_names(r)
            if _inf:
                # names whose spelling is a guess are marked, never shown like read ones
                out["inferred_names"] = _inf
                out["inferred_names_note"] = _kf.INFERRED_NAMES_NOTE
            if r.get("header"):
                # version, singleton, smart_selectable, name, reapplyable, typed, chunks
                out["header"] = {k: v for k, v in r["header"].items() if k != "size"}
        except Exception as e:
            out["lossless"] = False
            out["instances_source"] = "sweep"
            out["parse_error"] = str(e)[:200]
        if name_lower.endswith(".scene"):
            out["scene"] = scene_summary(out)
        return out
    if name_lower.endswith(".sequence"):
        return decode_sequence.parse(data, order=order)
    if name_lower.endswith(".terrain"):
        return terrain_json(data, order, stream)
    if name_lower.endswith(".terraincoloringasset"):
        import terrain_asset

        return terrain_asset.coloring_to_json(data, order)
    if name_lower.endswith(".font"):
        import font_asset

        return font_asset.to_json(data, order)
    if name_lower.endswith(".detailmesh"):
        return detailmesh_json(data, order, stream)
    if name_lower.endswith(".particle"):
        # the engine's grammar (loader 0x55d3ed): typed tree, format kapow-particle/2
        import particle_asset

        try:
            return particle_asset.to_json(data, order=order)
        except particle_asset.ParticleError as ex:
            out = kapow_props.parse(data, order=order)  # legacy block walk, never raises
            out.setdefault("warn", []).append("not a complete .particle tree: %s" % ex)
            return out
    if name_lower.endswith(".pb"):
        return pivot_book_json(data, order)
    if name_lower.endswith(PROPBAG_EXTS):
        return kapow_props.parse(data, order=order)
    return None


def pivot_book_json(data, order=None):
    """`.pb` -> the property bags (kapow_props.parse) plus the 12-byte header by name:
    `book_id` (u64 in the file's byte order: the first word is the low one on PC, the high
    one on Xbox 360 and PS3; Book +0x20, reader 0x528326) and `sheet_count`.  The first
    block keeps the three header words in `pre`.  Both keys are left out when the file
    does not start with a three-word header."""
    out = kapow_props.parse(data, order=order)
    blocks = out.get("blocks") if isinstance(out, dict) else None
    pre = blocks[0].get("pre") if blocks else None
    if pre and len(pre) == 3:
        big = (order or kapow_props.detect_order(data)) == ">"
        hi, lo = (pre[0], pre[1]) if big else (pre[1], pre[0])
        out["book_id"] = "0x%016x" % ((hi << 32) | lo)
        out["sheet_count"] = pre[2]
    return out


def undecoded(doc):
    """Why a JSON dict of to_json / export is NOT a complete decode of its asset, as a
    short text, or None when nothing is marked.  It reads the markers the decoders
    set, so the extract log and its per-kind summary say exactly what the JSON says:
    `not_decoded`, `parse_error`, `lossless` false, `unknown_keys`, `warn`, a byte
    count under `leftover_bytes` / `tail_bytes` / `trailing_bytes`, the same in the
    `stream` section, and `atlas_not_written` / `outputs_not_written` /
    `glb_not_written`.  `inferred` / `not_established` / `unverified` lists are about
    the MEANING of decoded fields and do not count."""
    if doc is None:
        return "no decoder output"
    why = []
    if doc.get("not_decoded"):
        nd = doc["not_decoded"]
        why.append(nd if isinstance(nd, str) else "not decoded: " + ", ".join(map(str, nd)))
    if doc.get("parse_error"):
        why.append("parse error: %s" % doc["parse_error"])
    elif doc.get("lossless") is False:
        why.append("the parse does not end at the file end")
    if doc.get("unknown_keys"):
        why.append("%d unknown key(s) typed by guess" % len(doc["unknown_keys"]))
    for k in ("leftover_bytes", "tail_bytes", "trailing_bytes"):
        if isinstance(doc.get(k), int) and doc[k] > 0 and not doc.get("not_decoded"):
            why.append("%d %s" % (doc[k], k.replace("_", " ")))
    st = doc.get("stream")
    if isinstance(st, dict):
        if st.get("not_decoded"):
            why.append("stream: %s" % st["not_decoded"])
        elif isinstance(st.get("leftover_bytes"), int) and st["leftover_bytes"] > 0:
            why.append("%d stream bytes left" % st["leftover_bytes"])
    for k in ("atlas_not_written", "outputs_not_written", "glb_not_written"):
        if doc.get(k):
            why.append("%s: %s" % (k.replace("_", " "), doc[k]))
    w = doc.get("warn")
    if w:
        why.append("; ".join(map(str, w)) if isinstance(w, (list, tuple)) else str(w))
    return "; ".join(why) or None


#: suffixes `export` handles itself (JSON plus images / a mesh beside the asset)
EXPORT_EXTS = (".font", ".scene", ".terrain", ".terraincoloringasset", ".detailmesh")


def export(name, data, stream=None, base=None, order=None, glb=True):
    """JSON dict and log lines for one asset of EXPORT_EXTS, writing the files that
    are not JSON beside `base` (the path of the raw asset as a string):
        .font                   <base>.png   the glyph atlas
        .terraincoloringasset   <base>.png   the map
        .terrain                <base>.height.png, <base>.layers.png, <base>.glb
    Returns (doc or None, [log lines]).  Nothing is left out silently: an asset or a
    part of it that is not decoded has a `not_decoded` / `leftover_bytes` /
    `trailing_bytes` / `tail_bytes` marker in the dict and a line in the list."""
    low = name.lower()
    lines = []
    if low.endswith(".font"):
        import font_asset

        doc = font_asset.to_json(data, order)
        wrote = False
        if base and doc.get("has_data"):
            try:
                wrote = font_asset.write_atlas(data, doc, base + ".png")
            except Exception as ex:
                doc["atlas_not_written"] = str(ex)[:200]
            if wrote:
                doc["atlas_png"] = base.replace("\\", "/").rsplit("/", 1)[-1] + ".png"
            else:
                doc.setdefault("atlas_not_written", "atlas format not decoded or no Pillow")
        lines += font_asset.notes(name, doc, wrote)
        return doc, lines
    if low.endswith(".terraincoloringasset"):
        import terrain_asset

        doc = terrain_asset.coloring_to_json(data, order)
        if base:
            try:
                terrain_asset.coloring_write(doc, stream, base)
            except Exception as ex:
                doc["stream"] = {"bytes": len(stream or b""), "not_decoded": str(ex)[:200]}
        lines += terrain_asset.coloring_notes(name, doc)
        return doc, lines
    if low.endswith(".terrain"):
        import terrain_asset

        doc = terrain_asset.to_json(data, order, stream)
        if base and not doc.get("not_decoded"):
            try:
                terrain_asset.write_outputs(doc, base, glb=glb)
            except Exception as ex:
                doc["outputs_not_written"] = str(ex)[:200]
                lines.append("WARNING: terrain %s: maps / GLB not written: %s" % (name, ex))
        terrain_asset.strip(doc)
        lines += terrain_asset.notes(name, doc)
        return doc, lines
    doc = to_json(low, data, order=order, stream=stream)
    if doc is None:
        return None, lines
    if low.endswith(".detailmesh"):
        if doc.get("trailing_bytes"):
            lines.append(
                "WARNING: detailmesh %s: %d trailing bytes not decoded"
                % (name, doc["trailing_bytes"])
            )
        st = doc.get("stream") or {}
        if st.get("not_decoded") or st.get("leftover_bytes"):
            lines.append(
                "WARNING: detailmesh %s: stream not fully decoded (%s)"
                % (name, st.get("not_decoded") or "%d bytes left" % st["leftover_bytes"])
            )
        elif st.get("stride_matches_format") is False:
            lines.append(
                "WARNING: detailmesh %s: vertex stride %d from the stream size, the format's "
                "is %d" % (name, st["vertex_stride"], st["format_stride"])
            )
    elif low.endswith(".scene"):
        if not doc.get("lossless"):
            lines.append(
                "WARNING: scene %s not decoded exactly: %s"
                % (name, doc.get("parse_error") or "the parse does not end at the file end")
            )
    return doc, lines


_FRAGMENT_FILES = {}


def load_fragment(path):
    """The fragment JSON of `path` (a `.fragment` or its `.fragment.json`).

    Parses the BINARY `.fragment` whenever it is there: a `.fragment.json` on
    disk may have been written by an older extractor (unnamed `key_xxxxxxxx`
    properties, a desynchronised EnemyDef in Dominatrices.fragment) and is only
    read when the binary is missing.  Cached per file (path, size, mtime)."""
    import os

    frag = path[:-5] if path.endswith(".json") else path
    if os.path.exists(frag):
        st = os.stat(frag)
        key = (os.path.abspath(frag), st.st_size, st.st_mtime_ns)
        if key not in _FRAGMENT_FILES:
            with open(frag, "rb") as fh:
                _FRAGMENT_FILES[key] = to_json(frag.lower(), fh.read())
        if _FRAGMENT_FILES[key]:
            return _FRAGMENT_FILES[key]
    with open(frag + ".json", encoding="utf-8") as fh:
        return json.load(fh)


_TREE_DIRS = {}  # root as given -> [open count, directories, their set, lower-cased set]


class tree_cache:
    """While open, glob_tree(root, ...) lists the directories under `root` once and
    answers every search from that list.  Open it only around work that does not
    add or remove directories under `root` (a metadata build reading a finished
    extract); outside it glob_tree is glob.glob itself.  Re-entrant."""

    def __init__(self, root):
        self.root = root

    def __enter__(self):
        _TREE_DIRS.setdefault(self.root, [0, None, None, None])[0] += 1
        return self

    def __exit__(self, *exc):
        slot = _TREE_DIRS[self.root]
        slot[0] -= 1
        if slot[0] <= 0:
            del _TREE_DIRS[self.root]
        return False


def glob_tree(root, *parts):
    """The paths glob.glob(os.path.join(root, "**", *parts), recursive=True) gives
    (in any order).  parts: literal directory names, then one file-name pattern.

    A recursive glob walks the whole tree for every pattern, and for a literal
    directory name asks the file system once per directory whether it is there;
    on a slow file system each of the half-dozen searches of a metadata build costs
    seconds.  Inside `tree_cache(root)` the tree is walked once: the directory list
    `**` expands to is kept, a literal name is looked up in it, and only the
    directories that have it are listed for the pattern."""
    import glob, os

    slot = _TREE_DIRS.get(root)
    if slot is None:
        return glob.glob(os.path.join(root, "**", *parts), recursive=True)
    if slot[1] is None:
        sep = (os.sep, os.altsep) if os.altsep else (os.sep,)
        dirs = []
        for d in glob.glob(os.path.join(root, "**", ""), recursive=True):
            while len(d) > 1 and d.endswith(sep):  # "root/" for the root, "root/a/" below
                d = d[:-1]
            dirs.append(d)
        slot[1], slot[2] = dirs, set(dirs)
        slot[3] = {d.lower() for d in dirs}
    literals, pattern = parts[:-1], parts[-1]
    out = []
    for d in slot[1]:
        cand = os.path.join(d, *literals) if literals else d
        if cand not in slot[2]:
            # glob finds a literal name with lexists: on a file system that ignores
            # case a directory spelled another way is found too
            if cand.lower() not in slot[3] or not os.path.lexists(cand):
                continue
        out.extend(glob.glob(os.path.join(glob.escape(cand), pattern)))
    return out


def find_fragment(root, stem):
    """Path of `<stem>.fragment` under `root` (recursive; the first in sorted
    order), found through the binary or, failing that, its `.fragment.json`.
    None when neither exists."""
    import glob, os

    hits = set()
    for ext in (".fragment", ".fragment.json"):
        for f in glob.glob(os.path.join(root, "**", stem + ext), recursive=True):
            hits.add(f[: -len(".json")] if f.endswith(".json") else f)
    return min(hits) if hits else None


if __name__ == "__main__":
    import sys

    b = _read_bytes(sys.argv[1])
    _sp = sys.argv[1] + ".stream"
    try:
        with open(_sp, "rb") as _f:
            _st = _f.read()
    except OSError:
        _st = None
    d = to_json(sys.argv[1].lower(), b, stream=_st)
    out = json.dumps(d, indent=1)
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8", newline="\n") as _f:
            _f.write(out)
    else:
        print(out[:4000])
