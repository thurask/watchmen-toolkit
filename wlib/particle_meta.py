#!/usr/bin/env python3
"""particle_meta -- every `.particle` of an extract as JSON plus one index
(`watchmen particlemeta EXTRACT_OUT OUT_DIR [TEXTURES_DIR]`).

    OUT_DIR/<asset path>.particle.json   the engine's tree of one file, format
                                         "kapow-particle/2" -- the same bytes `extract`
                                         writes beside the asset (kapow_json.to_json)
    OUT_DIR/index.json                   format "watchmen-particle-meta/1": per file the
                                         system's duration / loop, its particle types
                                         (name, texture, model, render style, blend mode,
                                         module classes), the textures and models it
                                         names resolved against the extract, class
                                         counts and the byte-exact rebuild check

Nothing here reads the executable or adds a fact of its own: the trees and every
value come from particle_asset (see docs/PARTICLE_FORMAT.md); this module walks
the extract, summarises and resolves references.

    find_particles(src) -> (root, [(path, rel)])
    build(src, textures=None) -> (index, {rel: per-file JSON})
    write(src, out_dir, textures=None, log=print) -> index
    summary(index) -> one line
"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)

import canonical_names  # noqa: E402
import particle_asset  # noqa: E402

FORMAT = "watchmen-particle-meta/1"

EVIDENCE = {
    "files": "data: every *.particle under EXTRACT_OUT/extracted, parsed with "
    "particle_asset (grammar read from the loader 0x55d3ed, see docs/PARTICLE_FORMAT.md)",
    "values": "particle_asset.values: the records of the file over the constructor "
    "defaults, with the two ParticleType setters applied (0x55733e, 0x557481)",
    "units": "read: duration and particleLife are seconds, particleSize metres; "
    "startTime / endTime are compared in seconds (0x55a722)",
    "uv_grid": "data: numX x numY of the type's UVArrayInitializer / UVArrayAffector "
    "(the texture is a grid of that many frames)",
    "textures": "the texture string of each ParticleType, looked up by its asset path "
    "(any case) in the extract's textures/ tree; no lookup by bare name",
    "names": "texture and model strings are spelled as the folder or file they name is "
    "written (the `dir` / `file` of their entry; a string that names nothing here has "
    "the spelling of wlib/canonical_names.json; --names stored: as the file stores "
    "them).  Where the files store another spelling: `stored_name` of the texture / "
    "model entry lists the spelling(s), and a file row and a type row hold their own "
    'strings under "stored".  The per-file JSON keeps the stored string',
    "models": "the model string of each ParticleType, looked up by its asset path "
    "(any case) under extracted/",
    "roundtrip": "particle_asset.build(parse(bytes)) == bytes",
}

#: ParticleType properties shown per type: (index key, engine property, enum table name)
_TYPE_FIELDS = (
    ("render_style", "renderStyle", "renderStyle"),
    ("blend_mode", "blendMode", "blendMode"),
    ("alignment", "alignment", "alignment"),
    ("simulation_mode", "simulationMode", "simulationMode"),
    ("max_particles", "maxParticles", None),
    ("particle_life_s", "particleLife", None),
    ("particle_size_m", "particleSize", None),
    ("start_time_s", "startTime", None),
    ("end_time_s", "endTime", None),
)
_UV_CLASSES = ("UVArrayInitializer", "UVArrayAffector")


def _key(rel):
    return (rel.lower(), rel)


def find_particles(src):
    """(root, [(path, rel)]) of the `.particle` files of `src`: an `extract` output
    (only its `extracted/` folder is walked), any other folder, or one file.
    `rel` is '/'-separated and relative to `root`; the list is sorted by it
    (lower case first), independent of the order the file system lists in."""
    src = str(src)
    if os.path.isfile(src):
        return os.path.dirname(os.path.abspath(src)), [(src, os.path.basename(src))]
    root = os.path.join(src, "extracted")
    if not os.path.isdir(root):
        root = src
    found = []
    for dp, dns, fns in os.walk(root):
        dns.sort()
        for f in fns:
            if f.lower().endswith(".particle"):
                p = os.path.join(dp, f)
                found.append((p, os.path.relpath(p, root).replace(os.sep, "/")))
    found.sort(key=lambda t: _key(t[1]))
    return root, found


def texture_tree(src, textures=None):
    """The folder the texture strings are looked up in: `textures` when given, else
    EXTRACT_OUT/textures (also when `src` is the `extracted` folder itself or a file
    below it).  None when there is none."""
    if textures:
        return str(textures) if os.path.isdir(str(textures)) else None
    p = os.path.abspath(str(src))
    cands = [os.path.join(p, "textures")]
    while True:
        parent = os.path.dirname(p)
        if parent == p:
            break
        if os.path.basename(p).lower() == "extracted":
            cands.append(os.path.join(parent, "textures"))
            break
        p = parent
    for c in cands:
        if os.path.isdir(c):
            return c
    return None


def _lookup(root, asset, cache=None):
    """Path of asset '/Art/x.bmp' below `root`, or None when it is not there.  Every
    component is taken from the directory listing -- as written when that name is
    listed, else the first name (sorted) that equals it ignoring case -- so the
    result has the names of the file system, also on a case-insensitive one.
    `cache` ({dir: sorted names}) saves listing a folder twice."""
    if not root or not isinstance(asset, str):
        return None
    parts = [x for x in asset.replace("\\", "/").split("/") if x not in ("", ".", "..")]
    if not parts:
        return None
    cache = {} if cache is None else cache
    cur = root
    for part in parts:
        names = cache.get(cur)
        if names is None:
            try:
                names = sorted(os.listdir(cur))
            except OSError:
                names = []
            cache[cur] = names
        if part not in names:
            hit = [n for n in names if n.lower() == part.lower()]
            if not hit:
                return None
            part = hit[0]
        cur = os.path.join(cur, part)
    return cur


def _rel(path, root):
    return os.path.relpath(path, root).replace(os.sep, "/")


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _disk_ref(ref, tree_root, cache=None):
    """An asset string in the spelling of the folder or file it names below
    `tree_root` (_lookup), a leading slash kept; one that names nothing there in
    the spelling of the table (canonical_names.canonical)."""
    hit = _lookup(tree_root, ref, cache)
    if hit is None:
        return canonical_names.canonical(ref, "canonical")
    parts = _rel(hit, tree_root).split("/")
    if parts == [x for x in ref.replace("\\", "/").split("/") if x]:
        return ref
    return ("/" if ref[:1] in "/\\" else "") + "/".join(parts)


def _canonical_ref(ref, stored=None, spell=None):
    """An asset string of a file in the spelling `spell` gives it (default: its
    canonical spelling, canonical_names); `stored` ({string written: [stored
    spellings]}) collects the ones that differ."""
    if not isinstance(ref, str) or not ref:
        return ref
    new = spell(ref) if spell else canonical_names.canonical(ref)
    if new != ref and stored is not None:
        known = stored.setdefault(new, [])
        if ref not in known:
            known.append(ref)
    return new


def type_row(index, t, stored=None, spell=None):
    """The index row of one ParticleType object of a parsed tree.  `spell`:
    (texture string -> spelling, model string -> spelling), see build()."""
    v = particle_asset.values(t)
    as_stored = {"texture": v.get("texture") or None, "model": v.get("model") or None}
    row = {
        "index": index,
        "name": v.get("name") or "",
        "texture": _canonical_ref(as_stored["texture"], stored, spell and spell[0]),
        "model": _canonical_ref(as_stored["model"], stored, spell and spell[1]),
    }
    for key, prop, enum in _TYPE_FIELDS:
        val = v.get(prop)
        if enum is not None and isinstance(val, int) and not isinstance(val, bool):
            val = particle_asset.ENUMS[enum].get(val, val)  # the item name, else the number
        row[key] = val
    for key, _role in particle_asset.LISTS:
        row[key] = [o["class"] for o in t.get(key, [])]
    for key, _role in particle_asset.LISTS:
        for o in t.get(key, []):
            if o["class"] in _UV_CLASSES and "uv_grid" not in row:
                m = particle_asset.values(o)
                if _num(m.get("numX")) is not None and _num(m.get("numY")) is not None:
                    row["uv_grid"] = {"x": m["numX"], "y": m["numY"], "from": o["class"]}
    differs = {k: x for k, x in as_stored.items() if x != row[k]}
    if differs:  # the strings the file stores, where the row spells them differently
        row[canonical_names.REF_STORED_KEY] = differs
    return row


def file_row(rel, data, tree, stored=None, spell=None):
    """The index row of one parsed file."""
    v = particle_asset.values(tree["system"])
    s = tree["summary"]
    types = [type_row(i, t, stored, spell) for i, t in enumerate(tree["types"])]
    as_stored = {}
    for field, key in (("textures", "texture"), ("models", "model")):
        raw = [(t.get(canonical_names.REF_STORED_KEY) or {}).get(key, t[key]) for t in types]
        if raw != [t[key] for t in types]:
            as_stored[field] = sorted(set(x for x in raw if x), key=_key)
    lives = [t["particle_life_s"] for t in types if _num(t["particle_life_s"]) is not None]
    caps = [t["max_particles"] for t in types if _num(t["max_particles"]) is not None]
    try:
        exact = particle_asset.build(tree) == data
    except Exception:  # a tree that cannot be written back is simply not exact
        exact = False
    row = {
        "file": rel,
        "asset": "/" + rel,
        "json": rel + ".json",
        "bytes": len(data),
        "parsed": True,
        "byte_order": tree["byte_order"],
        "record_layout": tree["record_layout"],
        "roundtrip": exact,
        "emit_duration_s": _num(v.get("duration")),
        "loop": v.get("loop") if isinstance(v.get("loop"), bool) else None,
        "types": len(types),
        "objects": s["objects"],
        "particle_life_s_max": max(lives) if lives else None,
        "max_particles_total": sum(caps),
        "textures": sorted(set(t["texture"] for t in types if t["texture"]), key=_key),
        "models": sorted(set(t["model"] for t in types if t["model"]), key=_key),
        "classes": s["classes"],
        "unknown_classes": len(s["unknown_classes"]),
        "unknown_properties": len(s["unknown_properties"]),
        "ignored_records": s["ignored_records"],
        "trailing_bytes": s["trailing_bytes"],
        "type_list": types,
    }
    if as_stored:  # the file's own strings, where the row spells them differently
        row[canonical_names.REF_STORED_KEY] = as_stored
    return row


def _texture_entry(asset, tree_root, cache=None):
    d = _lookup(tree_root, asset, cache)
    out = {"found": False, "dir": None, "images": [], "used_by": []}
    if d is None:
        return out
    out["found"] = True
    if os.path.isdir(d):
        out["dir"] = _rel(d, tree_root)
        try:
            out["images"] = sorted(n for n in os.listdir(d) if n.lower().endswith(".png"))
        except OSError:
            pass
    else:  # a tree of loose image files rather than carved texture folders
        out["dir"] = _rel(os.path.dirname(d), tree_root)
        out["images"] = [os.path.basename(d)]
    return out


def build(src, textures=None, log=None):
    """(index, docs) for the `.particle` files of `src` (see find_particles).
    `docs` maps each file's `rel` to its JSON document: the particle_asset tree, or
    for bytes that are not a complete tree what `extract` writes (the generic block
    walk with a `warn`).  Raises FileNotFoundError when `src` has no `.particle`."""
    import kapow_json

    root, found = find_particles(src)
    if not found:
        raise FileNotFoundError("no .particle file under %s" % src)
    tex_root = texture_tree(src, textures)
    rows, docs, errors = [], {}, []
    tex, models = {}, {}
    classes = {}
    listings = {}
    stored = {}  # asset string as written here -> the spellings the files store
    # --names canonical: a string is spelled as the folder / file it names is written
    canonical = (
        canonical_names.export_mode(os.path.dirname(tex_root) if tex_root else None) == "canonical"
    )
    if canonical:
        spell = (
            lambda ref: _disk_ref(ref, tex_root, listings),
            lambda ref: _disk_ref(ref, root, listings),
        )
    else:
        spell = (lambda ref: ref, lambda ref: ref)
    for path, rel in found:
        with open(path, "rb") as fh:
            data = fh.read()
        try:
            tree = particle_asset.parse(data)
        except particle_asset.ParticleError as ex:
            docs[rel] = kapow_json.to_json(rel.lower(), data)
            rows.append(
                {
                    "file": rel,
                    "asset": "/" + rel,
                    "json": rel + ".json",
                    "bytes": len(data),
                    "parsed": False,
                    "error": str(ex),
                }
            )
            errors.append({"file": rel, "error": str(ex)})
            if log:
                log("  ! %s: %s" % (rel, ex))
            continue
        docs[rel] = tree
        row = file_row(rel, data, tree, stored, spell)
        rows.append(row)
        if log and not row["roundtrip"]:
            log("  ! %s: does not rebuild byte-exact" % rel)
        for cls, n in row["classes"].items():
            classes[cls] = classes.get(cls, 0) + n
        for asset in row["textures"]:
            if asset not in tex:
                tex[asset] = _texture_entry(asset, tex_root, listings)
            tex[asset]["used_by"].append(rel)
        for asset in row["models"]:
            if asset not in models:
                p = _lookup(root, asset, listings)
                models[asset] = {
                    "found": p is not None,
                    "file": _rel(p, root) if p else None,
                    "used_by": [],
                }
            models[asset]["used_by"].append(rel)
    for asset, spellings in stored.items():
        for entry in (tex.get(asset), models.get(asset)):
            if entry is not None:
                entry[canonical_names.STORED_KEY] = sorted(spellings)
    good = [r for r in rows if r["parsed"]]
    index = {
        "format": FORMAT,
        "particle_format": particle_asset.FORMAT,
        "evidence": EVIDENCE,
        "texture_tree": os.path.basename(os.path.normpath(tex_root)) if tex_root else None,
        "counts": {
            "files": len(rows),
            "parsed": len(good),
            "failed": len(errors),
            "roundtrip_exact": sum(1 for r in good if r["roundtrip"]),
            "types": sum(r["types"] for r in good),
            "objects": sum(r["objects"] for r in good),
            "looping": sum(1 for r in good if r["loop"] is True),
            "byte_order": _tally(r["byte_order"] for r in good),
            "record_layout": _tally(r["record_layout"] for r in good),
            "unknown_classes": sum(r["unknown_classes"] for r in good),
            "unknown_properties": sum(r["unknown_properties"] for r in good),
            "ignored_records": sum(r["ignored_records"] for r in good),
            "textures": len(tex),
            "textures_found": sum(1 for t in tex.values() if t["found"]),
            "models": len(models),
            "models_found": sum(1 for m in models.values() if m["found"]),
        },
        "classes": dict(sorted(classes.items())),
        "files": rows,
        "textures": {k: tex[k] for k in sorted(tex, key=_key)},
        "models": {k: models[k] for k in sorted(models, key=_key)},
        "errors": errors,
    }
    if canonical:
        index[canonical_names.NAMES_KEY] = {
            "spelling": "export",
            "respelled": respelled(index),
            "note": NAMES_NOTE,
        }
    return index, docs


#: `asset_names.note` of the index
NAMES_NOTE = (
    "A texture or model string is spelled as the folder or file it names is written "
    "(the `dir` / `file` of its entry under `textures` / `models`), so it finds it on "
    "a case-sensitive file system.  `respelled` counts the strings written in another "
    "spelling than the files store: each `texture` / `model` of a type row, each "
    "string of a file row's `textures` / `models` list, and each key of `textures` / "
    '`models` that has a `stored_name`.  The stored strings are under "stored" of '
    "the row and `stored_name` of the entry.  --names stored: every string as the file "
    "stores it, and no `asset_names`."
)


def respelled(index):
    """The number of strings of an index written in another spelling than the
    files store (NAMES_NOTE says which are counted)."""
    key = canonical_names.REF_STORED_KEY
    n = 0
    for row in index["files"]:
        for field, raw in (row.get(key) or {}).items():
            n += len(set(raw) - set(row.get(field) or ()))
        for t in row.get("type_list") or ():
            n += len(t.get(key) or {})
    for table in ("textures", "models"):
        n += sum(1 for e in index[table].values() if canonical_names.STORED_KEY in e)
    return n


def _tally(values):
    out = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items()))


def write(src, out_dir, textures=None, log=print):
    """Write OUT_DIR/<rel>.json for every `.particle` of `src` and OUT_DIR/index.json.
    -> the index.  Raises FileNotFoundError when there is no `.particle`."""
    index, docs = build(src, textures=textures, log=log)
    out_dir = str(out_dir)
    for row in index["files"]:
        path = os.path.join(out_dir, *row["json"].split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(docs[row["file"]], indent=1))  # as `extract` writes it
    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(index, fh, indent=1)
    return index


def summary(index):
    c = index["counts"]
    text = "%d particle files (%d parsed, %d rebuild byte-exact), %d types, %d objects" % (
        c["files"],
        c["parsed"],
        c["roundtrip_exact"],
        c["types"],
        c["objects"],
    )
    if index["texture_tree"] is None:
        text += ", %d textures named (no texture tree to look them up in)" % c["textures"]
    else:
        text += ", %d of %d textures found" % (c["textures_found"], c["textures"])
    if c["models"]:
        text += ", %d of %d models found" % (c["models_found"], c["models"])
    return text


def main(argv):
    if len(argv) not in (2, 3):
        print("usage: particle_meta.py EXTRACT_OUT OUT_DIR [TEXTURES_DIR]", file=sys.stderr)
        return 2
    if not os.path.exists(argv[0]):
        print("error: %s does not exist" % argv[0], file=sys.stderr)
        return 2
    textures = argv[2] if len(argv) > 2 else None
    if textures is not None and not os.path.isdir(textures):
        print("error: %s is not a directory" % textures, file=sys.stderr)
        return 2
    try:
        index = write(argv[0], argv[1], textures=textures, log=print)
    except FileNotFoundError as ex:
        print("error: %s" % ex, file=sys.stderr)
        return 1
    print("wrote %s: %s" % (os.path.join(argv[1], "index.json"), summary(index)))
    return 1 if index["counts"]["failed"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
