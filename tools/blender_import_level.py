#!/usr/bin/env python3
"""Import a watchmen level (``<Level>.level.json``) into Blender.

Every model GLB the level uses is imported once, into a switched-off "Library" collection,
and every placement becomes an empty that instances the model's collection at the ``gltf``
transform of the level file.  The terrain, the sky, the placed characters (posed with their
idle clip) and the navigation mesh are added, and everything is sorted into collections.

Two ways to run it:

* inside Blender: Scripting workspace > Text > Open > this file > Run Script.  A file browser
  opens: pick a ``*.level.json``.  The script also adds File > Import > "Watchmen level
  (.level.json)" for the rest of the session.
* from a shell::

      blender -b --python tools/blender_import_level.py -- LEVEL.json [--save OUT.blend]
          [--no-characters] [--no-sky] [--no-nav] [--include-disabled] [--limit N]
          [--keep-duplicate-images] [--compress]

  Without ``-b`` Blender stays open with the level in it.

The level file must lie in the export it was written with: ``<export>/levels/<Level>.level.json``
beside ``models/``, ``textures/``, ``extracted/``, ``characters_v<version>/`` and ``nav/``.
Every path is taken from the level file's own strings, so the level file must use the naming of
its export: ``levelmeta`` follows the export's ``--names`` (default ``canonical``) unless the
option is given.

What goes where (collections, all below one collection named like the level)::

    <Level> Terrain       the terrain GLB at files.terrain[].gltf, one object per texture layer
    <Level> Props         one sub-collection per level section (the PVS fragment a placement
                          lies in: a room, a city block), instances inside
    <Level> Characters    one sub-collection per character folder; "Scene models" (switched
                          off) holds the part models of placed Character nodes, bind pose
    <Level> Sky           the placements whose model lies below .../environments/sky/
    <Level> Navigation    <Level>.nav.glb, switched off
    <Level> Disabled, <Level> Invisible     only with --include-disabled
    <Level> Host-offset copies    switched off: the records the level file marks with
                          ``host_offset_copy`` (see below)
    <Level> Library       one collection per GLB, switched off (the instances still show)

An instance is an empty with ``instance_type = 'COLLECTION'``, not a linked duplicate of the
mesh object: a model or character GLB can hold several objects (an armature and its meshes,
a model of several parts), and a collection instance keeps them together under one
transform.  To edit one placement on its own use Object > Apply > Make Instances Real.

Each instance carries custom properties (``watchmen_uid``, ``watchmen_node_id``,
``watchmen_fragment``, ``watchmen_section``, ``watchmen_model``, ...) that lead back to the
record in the level file.  ``watchmen_visible_effective`` is the level file's
``visible_effective`` (the node's flag and its ``PVSRootNode`` ancestors', engine 0x48e028); the
importer sorts by the node's own ``visible``, because the game switches PVS roots at
run time (StreetsOfRiot keeps 36 background characters under six invisible ones).  The
materials are the ones Blender's glTF importer builds; only
the terrain, whose GLB has no texture, gets a material of its own (layer texture times the
vertex tint when the texture is in the export, plain grey otherwise).

Characters: a placement gets ``characters_v<version>/<folder>/<variant>.glb`` of the variant
the level file fixes.  Where the game picks the least-used member of a collection at run
time, the candidates are handed out in turn, in the order of the level file's
``characters[]`` (``watchmen_variant_pick = "candidate_in_turn"``, the member in
``watchmen_variant_member``, the candidates in ``watchmen_variant_candidates``): member 1
for the first character of a kind, then 2, 3, ... round the list.  The order in which the
game builds the characters is not known, so which character wears which outfit is one
possible hand-out, not the game's.  Members that share one GLB are its outfits
(``watchmen_outfit``, the ``OUTFIT <k> ...`` nodes of ``asset.extras.watchmen.parts``); the
face is that of outfit 1.  A GLB is imported once per variant and outfit, without the other
outfits, the weapons and the ragdoll helpers, and with one clip, the idle stand, which poses
it and plays on the timeline.  The instance sits CHARACTER_PIVOT_HEIGHT (1 m) above the
placement along the placement's own up axis, because a character GLB has its origin that far
above its soles.

Host-offset copies: a record with ``host_offset_copy`` (LEVEL_META.md, "Host-offset
copies": a model node left in level coordinates under a moved fragment host, ten
``CharacterSimple`` nodes 50 m above the street in StreetsOfRiot) is placed where the level
file puts it, but in "<Level> Host-offset copies", which is switched off, and not among the
visible ones.  Whether the game draws these nodes is not established; switch the collection
on to see them.  Each carries ``watchmen_host_offset_copy`` and, when it has one,
``watchmen_host_offset_twin`` (the uid of the placed node).  The placed nodes themselves
(36 in StreetsOfRiot) stay in the switched-off "Scene models": the level file gives each
``visible_effective`` false under an invisible ``PVSRootNode``.

Sky instances are visible to the camera only (no shadow, diffuse or glossy rays), so a dome
does not shadow a sun placed outside it.  Identical images that several GLBs embed are
merged into one datablock while the library is built.  The scene's lights, world and frame
range are left alone.  A level that is already in the file is refused; when an import fails
the partial level stays, with its Library switched off, and has to be deleted by hand.

The functions above the "Blender side" line need no ``bpy`` and are tested in
``tests/test_blender_import_level.py``.  Checked with Blender 3.6 (bpy 3.6.0); written for
3.6 to 5.2.  The only 5.x result: the level import was run by the user on desktop Blender 5.2
through the Scripting tab without errors and was not inspected in detail.
"""

import json
import os
import re
import shutil
import struct
import sys
import time

FRAME_TRUE = "right-handed-true"
FRAME_MIRRORED = "mirrored"
LEVEL_FORMAT = "watchmen-level-meta/1"

#: A character GLB has its origin at ``GamePivot``, 1.0 m above the soles in every skeleton
#: (docs/ANIMATION_META.md, "Body joints are keyed relative to GamePivot"); a placement is a
#: point on the floor.
CHARACTER_PIVOT_HEIGHT = 1.0
# the group (collection below the level collection, switched off) of the model records the
# level file marks with host_offset_copy; whether the game draws them is not established
HOST_OFFSET_GROUP = ("Host-offset copies",)

#: Identical images are merged after every DEDUPE_EVERY imported GLBs (and at the end).
DEDUPE_EVERY = 25

#: The clip a placed character is posed with: the first pattern that matches a clip name.
IDLE_PATTERNS = (r"_EXP_MOV_idle_stand$", r"_MOV_idle_stand$", r"idle_stand", r"idle")


class LevelError(Exception):
    """The level file cannot be imported as asked; the message says why."""


# --------------------------------------------------------------------------------------
# GLB container
# --------------------------------------------------------------------------------------


def glb_json(path):
    """The JSON chunk of a GLB file as a dict."""
    with open(path, "rb") as fh:
        head = fh.read(12)
        if len(head) < 12 or head[:4] != b"glTF":
            raise ValueError("%s is not a GLB file" % path)
        while True:
            ch = fh.read(8)
            if len(ch) < 8:
                raise ValueError("%s has no JSON chunk" % path)
            n, kind = struct.unpack("<I4s", ch)
            if kind == b"JSON":
                return json.loads(fh.read(n).decode("utf-8"))
            fh.seek(n, 1)


def glb_frame(doc):
    """FRAME_TRUE or FRAME_MIRRORED: the frame a toolkit GLB (its JSON chunk) is written in.
    A file without the marker is in the mirrored (1.3.0) frame."""
    ex = ((doc.get("asset") or {}).get("extras") or {}).get("watchmen") or {}
    cf = ex.get("coordinate_frame")
    if cf is None:
        return FRAME_MIRRORED
    if cf == FRAME_TRUE:
        return FRAME_TRUE
    raise LevelError("unknown coordinate_frame %r in a GLB" % (cf,))


def write_glb(path, doc, src):
    """Write the GLB `path` with the JSON `doc` and the binary chunks of the GLB `src`."""
    js = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    with open(src, "rb") as fi:
        fi.seek(12)
        chunks = []
        while True:
            ch = fi.read(8)
            if len(ch) < 8:
                break
            n, kind = struct.unpack("<I4s", ch)
            if kind == b"JSON":
                fi.seek(n, 1)
            else:
                chunks.append((kind, fi.tell(), n))
                fi.seek(n, 1)
        total = 12 + 8 + len(js) + sum(8 + n for _, _, n in chunks)
        with open(path, "wb") as fo:
            fo.write(struct.pack("<4sII", b"glTF", 2, total))
            fo.write(struct.pack("<I4s", len(js), b"JSON"))
            fo.write(js)
            for kind, off, n in chunks:
                fo.write(struct.pack("<I4s", n, kind))
                fi.seek(off)
                left = n
                while left:
                    buf = fi.read(min(left, 1 << 22))
                    if not buf:
                        raise ValueError("%s is truncated" % src)
                    fo.write(buf)
                    left -= len(buf)


def pick_idle(names):
    """The clip of `names` a placed character is posed with (IDLE_PATTERNS, case
    ignored, the first name in file order that matches the first pattern), or None."""
    for pat in IDLE_PATTERNS:
        rx = re.compile(pat, re.I)
        for n in names:
            if n and not n.startswith(("FACE ", "GRIP ")) and rx.search(n):
                return n
    return None


def outfit_swap(doc, outfit):
    """(names of the nodes to take out of the scene, names of the nodes to put in) to show
    outfit `outfit` (1-based: ``asset.extras.watchmen.parts.members[].index``) of a
    character GLB, or None when the file does not hold that outfit as nodes of its own
    (a GLB with one outfit, a number past the list)."""
    parts = (((doc.get("asset") or {}).get("extras") or {}).get("watchmen") or {}).get("parts")
    if not isinstance(parts, dict):
        return None
    members = {m.get("index"): m for m in parts.get("members") or [] if isinstance(m, dict)}
    want = members.get(outfit)
    if want is None or "nodes" not in want:
        return None
    shown = members.get(parts.get("member_shown")) or {}
    out = list(parts.get("shown_nodes") or shown.get("nodes") or [])
    return out, list(want.get("nodes") or [])


def prune_gltf(doc, keep_animation=None, outfit=None):
    """A copy of the glTF JSON `doc` with the nodes of the scene only and at most one
    animation; with `outfit` (see outfit_swap) the nodes of that outfit take the place of
    the outfit the scene shows.

    A character GLB keeps the other outfits, the weapons and the ragdoll helpers as nodes
    outside the scene, and a few hundred clips: none of that is wanted on a placed
    character, and the clips are what makes the import slow.  Kept: every node reachable
    from the scene's roots, the joints of the skins those nodes use (with their
    ancestors), and the animation named `keep_animation`.  Meshes, materials, images and
    accessors stay as they are; an importer reads only what a node refers to."""
    doc = json.loads(json.dumps(doc))
    nodes = doc.get("nodes") or []
    scenes = doc.get("scenes") or []
    scene = scenes[doc.get("scene", 0)] if scenes else {"nodes": list(range(len(nodes)))}
    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get("children") or []:
            parent[c] = i
    swap = outfit_swap(doc, outfit) if outfit is not None else None
    if swap:
        index = {n.get("name"): i for i, n in enumerate(nodes)}
        out = [index[x] for x in swap[0] if x in index]
        new = [index[x] for x in swap[1] if x in index]
        if new or not swap[1]:
            host = parent.get(out[0]) if out else None
            for i in set(out) - set(new):
                p = parent.pop(i, None)
                if p is not None:
                    nodes[p]["children"] = [c for c in nodes[p]["children"] if c != i]
                else:
                    scene["nodes"] = [c for c in scene.get("nodes") or [] if c != i]
            for i in new:
                if i in out:
                    continue
                p = parent.pop(i, None)
                if p is not None:
                    nodes[p]["children"] = [c for c in nodes[p]["children"] if c != i]
                if host is not None:
                    nodes[host].setdefault("children", []).append(i)
                    parent[i] = host
                else:
                    scene["nodes"] = list(scene.get("nodes") or []) + [i]
    keep = set()
    stack = list(scene.get("nodes") or [])
    while stack:
        i = stack.pop()
        if i in keep:
            continue
        keep.add(i)
        stack.extend(nodes[i].get("children") or [])
    skins = doc.get("skins") or []
    used_skins = sorted({nodes[i]["skin"] for i in keep if "skin" in nodes[i]})
    extra_roots = []
    for s in used_skins:
        for j in list(skins[s].get("joints") or []) + (
            [skins[s]["skeleton"]] if "skeleton" in skins[s] else []
        ):
            while j not in keep:
                keep.add(j)
                if j in parent:
                    j = parent[j]
                else:
                    extra_roots.append(j)
                    break
    order = sorted(keep)
    remap = {old: new for new, old in enumerate(order)}
    skin_map = {old: new for new, old in enumerate(used_skins)}
    out_nodes = []
    for old in order:
        n = dict(nodes[old])
        if "children" in n:
            ch = [remap[c] for c in n["children"] if c in remap]
            if ch:
                n["children"] = ch
            else:
                del n["children"]
        if "skin" in n:
            n["skin"] = skin_map[n["skin"]]
        out_nodes.append(n)
    doc["nodes"] = out_nodes
    new_scene = dict(scene)
    new_scene["nodes"] = [remap[i] for i in list(scene.get("nodes") or []) + extra_roots]
    doc["scenes"] = [new_scene]
    doc["scene"] = 0
    if skins:
        out_skins = []
        for s in used_skins:
            sk = dict(skins[s])
            sk["joints"] = [remap[j] for j in sk.get("joints") or []]
            if "skeleton" in sk:
                sk["skeleton"] = remap[sk["skeleton"]]
            out_skins.append(sk)
        if out_skins:
            doc["skins"] = out_skins
        else:
            del doc["skins"]
    anims = []
    for a in doc.get("animations") or []:
        if keep_animation is None or a.get("name") != keep_animation:
            continue
        a = dict(a)
        chans = []
        for c in a.get("channels") or []:
            tgt = dict(c.get("target") or {})
            if tgt.get("node") in remap:
                tgt["node"] = remap[tgt["node"]]
                c = dict(c)
                c["target"] = tgt
                chans.append(c)
        if chans:
            a["channels"] = chans
            anims.append(a)
        break
    if anims:
        doc["animations"] = anims
    else:
        doc.pop("animations", None)
    return doc


# --------------------------------------------------------------------------------------
# The export on disk
# --------------------------------------------------------------------------------------


def find_export_root(level_path):
    """The export folder of a level file: the folder that holds ``models/``, looked for
    from the level file upwards (normally the parent of ``levels/``)."""
    d = os.path.dirname(os.path.abspath(level_path))
    for _ in range(4):
        if os.path.isdir(os.path.join(d, "models")):
            return d
        up = os.path.dirname(d)
        if up == d:
            break
        d = up
    raise LevelError(
        "no models/ folder beside or above %s: the level file must lie in its export "
        "(<export>/levels/<Level>.level.json beside models/, textures/, extracted/)"
        % os.path.dirname(os.path.abspath(level_path))
    )


def join_export(root, *parts):
    """`root` joined with export strings ("/art/props/x.model"), exact case."""
    segs = []
    for p in parts:
        segs.extend(s for s in p.replace("\\", "/").split("/") if s and s != ".")
    if ".." in segs:
        raise LevelError("path %r leaves the export" % "/".join(parts))
    return os.path.join(root, *segs)


def resolve_nocase(root, rel):
    """`root`/`rel` with every component matched without regard to case, or None.  Only
    for the strings that are kept as the game stores them (a terrain layer's texture)."""
    cur = root
    for seg in [s for s in rel.replace("\\", "/").split("/") if s and s != "."]:
        if seg == "..":
            return None
        cand = os.path.join(cur, seg)
        if not os.path.exists(cand):
            low = seg.lower()
            try:
                hit = sorted(n for n in os.listdir(cur) if n.lower() == low)
            except OSError:
                return None
            if not hit:
                return None
            cand = os.path.join(cur, hit[0])
        cur = cand
    return cur


def model_glb(root, model):
    """The GLB of a level file's model string: ``models/<path>.glb``."""
    return join_export(root, "models", model + ".glb")


def terrain_glb(root, entry):
    """The GLB of a ``files.terrain`` entry: below ``extracted/``, else ``files/data/`` or
    ``files/`` (the first that exists; the ``extracted/`` path when none does)."""
    name = entry.get("glb") or (entry.get("asset") or "") + ".glb"
    cands = [join_export(root, sub, name) for sub in ("extracted", "files/data", "files")]
    for c in cands:
        if os.path.isfile(c):
            return c
    return cands[0]


def nav_glb(root, level_name):
    return os.path.join(root, "nav", level_name + ".nav.glb")


def characters_dir(root):
    """The folder ``watchmen characters`` wrote into this export: ``characters_v<version>``
    (the last in name order when there are several), else ``characters``; None when the
    export has neither."""
    try:
        names = sorted(
            n
            for n in os.listdir(root)
            if n.lower().startswith("characters") and os.path.isdir(os.path.join(root, n))
        )
    except OSError:
        return None
    versioned = [n for n in names if n.lower().startswith("characters_v")]
    pick = versioned[-1] if versioned else (names[-1] if names else None)
    return os.path.join(root, pick) if pick else None


def texture_png(root, texture, layer="0_diffuse"):
    """The PNG of one layer of an extracted texture (``textures/<path>/<layer>_*.png``), or
    None.  `texture` may be spelled as the game stores it."""
    d = resolve_nocase(os.path.join(root, "textures"), texture)
    if not d or not os.path.isdir(d):
        return None
    for n in sorted(os.listdir(d)):
        if n.startswith(layer) and n.lower().endswith(".png"):
            return os.path.join(d, n)
    return None


# --------------------------------------------------------------------------------------
# The level file
# --------------------------------------------------------------------------------------


def load_level(path):
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict) or doc.get("format") != LEVEL_FORMAT:
        raise LevelError(
            "%s is not a %s file (format: %r)"
            % (path, LEVEL_FORMAT, doc.get("format") if isinstance(doc, dict) else None)
        )
    return doc


def level_frame(doc):
    """FRAME_TRUE or FRAME_MIRRORED for a level document; LevelError for anything else.
    A level file without ``coordinate_frame`` was written with ``--frame mirrored``."""
    cf = doc.get("coordinate_frame")
    if cf is None:
        return FRAME_MIRRORED
    if cf == FRAME_TRUE:
        return FRAME_TRUE
    raise LevelError(
        "the level file has coordinate_frame %r; this importer knows %r and files without "
        "the key (--frame mirrored)" % (cf, FRAME_TRUE)
    )


def gltf_to_blender(translation, rotation):
    """A glTF node transform as Blender's importer converts it: location (x, -z, y) and
    quaternion (w, x, -z, y) from translation (x, y, z) and rotation (x, y, z, w)."""
    x, y, z = (float(v) for v in translation)
    qx, qy, qz, qw = (float(v) for v in rotation)
    return (x, -z, y), (qw, qx, -qz, qy)


def placement_trs(rec, lift=0.0):
    """(location, quaternion wxyz) in Blender space of a level record with a ``gltf``
    block, moved `lift` metres along the record's own up axis (Blender +Z turned by the
    quaternion), so that a tilted character keeps its soles on the placement."""
    g = rec["gltf"]
    loc, quat = gltf_to_blender(g["translation"], g["rotation"])
    if not lift:
        return loc, quat
    w, x, y, z = quat
    n = w * w + x * x + y * y + z * z
    if n <= 0.0:
        return (loc[0], loc[1], loc[2] + lift), quat
    s = 2.0 / n
    up = (s * (x * z + w * y), s * (y * z - w * x), 1.0 - s * (x * x + y * y))
    return (loc[0] + lift * up[0], loc[1] + lift * up[1], loc[2] + lift * up[2]), quat


def _stem(path):
    b = path.replace("\\", "/").rsplit("/", 1)[-1]
    for ext in (".model.glb", ".terrain.glb", ".nav.glb", ".glb", ".model", ".fragment"):
        if b.lower().endswith(ext):
            return b[: -len(ext)]
    return b


def object_name(stem, uid, limit=63):
    """A unique, traceable object name: ``<stem> <uid>`` within Blender's name limit."""
    tail = " " + uid
    return stem[: max(1, limit - len(tail))] + tail


def is_sky(model):
    """Does a model string name a sky model (a file below ``.../environments/sky/``)?"""
    return "/environments/sky/" in model.replace("\\", "/").lower()


def sections(doc):
    """{fragment instance index: section name}.  The section of a fragment instance is the
    nearest fragment at or above it that belongs to the level's own folder (a PVS room or
    city block, ``gameplay``, ``Gameplay/MissionStructure``): its path below the level
    folder without ``PVS/`` and ``.fragment``.  Instances of the top fragment and instances
    with no such ancestor are in ``<level>``."""
    top = (doc.get("files") or {}).get("top_fragment") or (doc.get("level") or {}).get("asset")
    top = top or ""
    level_dir = top.rsplit("/", 1)[0] + "/"
    name = (doc.get("level") or {}).get("name") or _stem(top) or "level"
    frags = {f["index"]: f for f in doc.get("fragments") or []}
    memo = {}

    def own(i):
        chain = []
        res = name
        while i is not None and i in frags:
            if i in memo:
                res = memo[i]
                break
            chain.append(i)
            a = frags[i].get("asset") or ""
            if a != top and level_dir != "/" and a.lower().startswith(level_dir.lower()):
                rel = a[len(level_dir) :]
                if rel.lower().endswith(".fragment"):
                    rel = rel[: -len(".fragment")]
                if rel.lower().startswith("pvs/"):
                    rel = rel[4:]
                res = rel
                break
            i = frags[i].get("parent")
        for c in chain:
            memo[c] = res
        return res

    return {i: own(i) for i in frags}


def instance_index(uid):
    """The fragment instance index of a ``uid`` (``<index>:<node id>``), or None."""
    try:
        return int(str(uid).split(":", 1)[0])
    except ValueError:
        return None


def character_choice(doc, rec, chars_dir, turn=0):
    """Which character GLB a ``characters[]`` record gets: a dict with ``glb`` (path or
    None), ``character`` (folder), ``variant`` (file stem), ``pick``, ``candidates``,
    ``member`` (index in the definition's member list) and ``outfit`` (1-based number of
    the outfit inside the GLB).

    ``pick``: ``fixed`` (the level file fixes the member), ``candidate_in_turn`` (the game
    takes the least-used member of ``candidates`` at run time, the first in list order on
    a tie: the `turn`-th character of a definition gets candidate ``turn % len``, the next
    one with a file when that one has none), ``first_candidate`` (any other status: the
    first member), ``scene_model`` (a hero: the model the level's LevelSceneCtrl names) or
    ``folder_default`` (the member has no name or no file: the folder's own GLB).

    Members of one name share a GLB and are its outfits in member order: ``outfit`` is 1
    plus the number of members of that name before the chosen one."""
    exp = rec.get("export") or {}
    folder = exp.get("character") or ""
    var = rec.get("variant") or {}
    status = var.get("status")
    ctype = (rec.get("character_type") or {}).get("value")
    cdef = (doc.get("character_defs") or {}).get(str(ctype)) or {}
    members = {m.get("index"): m for m in (cdef.get("export") or {}).get("members") or []}
    idx = list(var.get("members") or [])
    names = [(members.get(i) or {}).get("name") or "" for i in idx]
    out = {
        "character": folder,
        "variant": None,
        "glb": None,
        "pick": None,
        "candidates": ["%s:%s" % (i, n) for i, n in zip(idx, names) if n],
        "status": status,
        "member": None,
        "outfit": 1,
    }
    if not chars_dir or not folder:
        return out
    base = os.path.join(chars_dir, folder)

    def have(stem):
        return bool(stem) and os.path.isfile(os.path.join(base, stem + ".glb"))

    choice = None
    if status == "fixed_scene_model":
        hero = (doc.get("level") or {}).get("hero_models") or {}
        key = "rsh" if folder.lower().startswith("rorschach") else "nto"
        model = ((hero.get(key) or {}).get("model") or "").lower()
        for stem in ([folder + "_Dry"] if "dry" in model else []) + [folder]:
            if have(stem):
                choice = (stem, "scene_model")
                break
    elif names and status == "candidates":
        for step in range(len(names)):
            j = (turn + step) % len(names)
            if have(names[j]):
                choice = (names[j], "candidate_in_turn")
                out["member"] = idx[j]
                break
    elif names and have(names[0]):
        choice = (names[0], "fixed" if status == "fixed" else "first_candidate")
        out["member"] = idx[0]
    if out["member"] is not None:
        out["outfit"] = 1 + sum(
            1
            for i, m in members.items()
            if isinstance(i, int) and i < out["member"] and (m.get("name") or "") == choice[0]
        )
    if choice is None:
        if have(folder):
            choice = (folder, "folder_default")
        elif os.path.isdir(base):
            glbs = sorted(n for n in os.listdir(base) if n.lower().endswith(".glb"))
            if glbs:
                choice = (glbs[0][:-4], "folder_default")
    if choice:
        out["variant"], out["pick"] = choice
        out["glb"] = os.path.join(base, choice[0] + ".glb")
    return out


def _props(**kw):
    return {"watchmen_" + k: v for k, v in kw.items() if v is not None and v != ""}


def build_plan(
    doc, root, level_path=None, characters=True, sky=True, nav=True, disabled=False, limit=0
):
    """What an import creates, without Blender: a dict with

    ``level``, ``frame``, ``terrain`` (list of {glb, name, loc, quat, props, textures}),
    ``nav`` (path or None), ``instances`` (list of {kind, group, name, glb, loc, quat,
    props, character, outfit}) and ``counts`` / ``skipped`` / ``missing``.

    ``kind`` is ``prop``, ``sky``, ``character``, ``scene_model``; ``group`` is the
    collection path below the level collection, e.g. ("Props", "01_TWM_Attrium").  A
    record that is disabled or invisible goes to ("Disabled",) / ("Invisible",) with
    `disabled`, and is counted in ``skipped`` without it.  An enabled, visible record with
    ``host_offset_copy`` goes to HOST_OFFSET_GROUP whatever its kind and is counted in
    ``counts["host_offset_copies"]``.  `limit` > 0 keeps the first
    `limit` model placements (a quick look)."""
    frame = level_frame(doc)
    name = (doc.get("level") or {}).get("name") or _stem(level_path or "level")
    sect = sections(doc)
    plan = {
        "level": name,
        "frame": frame,
        "root": root,
        "terrain": [],
        "nav": None,
        "instances": [],
        "counts": {},
        "skipped": {},
        "missing": {},
    }
    counts, skipped, missing = plan["counts"], plan["skipped"], plan["missing"]

    def bump(d, k, n=1):
        d[k] = d.get(k, 0) + n

    for t in (doc.get("files") or {}).get("terrain") or []:
        if not t.get("gltf"):
            continue
        if not (t.get("enabled_effective", True) and t.get("visible", True)) and not disabled:
            bump(skipped, "terrain_disabled")
            continue
        path = terrain_glb(root, t)
        loc, quat = placement_trs(t)
        plan["terrain"].append(
            {
                "glb": path,
                "name": _stem(path),
                "loc": loc,
                "quat": quat,
                "props": _props(
                    level=name, uid=t.get("uid"), fragment=t.get("fragment"), asset=t.get("asset")
                ),
            }
        )
        if not os.path.isfile(path):
            bump(missing, path)

    placed = 0
    for m in doc.get("models") or []:
        bump(counts, "model_placements")
        models = m.get("models") or []
        role = m.get("role") or "prop"
        off = (not m.get("enabled", True) and "Disabled") or (
            not m.get("visible", True) and "Invisible"
        )
        sky_rec = role == "prop" and any(is_sky(x) for x in models)
        if role != "prop" and (off or not characters):
            # definition variants and hero models kept in level data: never drawn as placed
            bump(skipped, "character_models_disabled" if off else "character_models")
            continue
        if off and not disabled:
            bump(skipped, "props_" + off.lower())
            continue
        if sky_rec and not sky and not off:
            bump(skipped, "sky")
            continue
        if limit and placed >= limit:
            bump(skipped, "over_limit")
            continue
        placed += 1
        section = sect.get(instance_index(m.get("uid")), name)
        if off:
            kind, group = ("sky" if sky_rec else "prop"), (off,)
        elif role != "prop":
            kind, group = "scene_model", ("Characters", "Scene models")
        elif sky_rec:
            kind, group = "sky", ("Sky",)
        else:
            kind, group = "prop", ("Props", section)
        copy = m.get("host_offset_copy")
        if isinstance(copy, dict) and not off:
            group = HOST_OFFSET_GROUP
            bump(counts, "host_offset_copies")
        loc, quat = placement_trs(m)
        uid = m.get("uid") or ""
        cube = (m.get("cube_map") or {}).get("texture")
        any_glb = False
        for model in models:
            path = model_glb(root, model)
            if not os.path.isfile(path):
                if role != "prop":
                    # a Character node lists its skeleton first: a .model without a mesh
                    bump(skipped, "scene_model_parts_without_glb")
                    continue
                bump(missing, path)
                path = None
            any_glb = any_glb or path is not None
            plan["instances"].append(
                {
                    "kind": kind,
                    "group": group,
                    "name": object_name(_stem(model), uid),
                    "glb": path,
                    "loc": loc,
                    "quat": quat,
                    "props": _props(
                        level=name,
                        kind=kind,
                        uid=uid,
                        node_id=uid.split(":", 1)[-1],
                        fragment=m.get("fragment"),
                        section=section,
                        model=model,
                        node_class=m.get("class"),
                        node_name=m.get("name"),
                        enabled=bool(m.get("enabled", True)),
                        visible=bool(m.get("visible", True)),
                        visible_effective=m.get("visible_effective"),
                        opacity=m.get("opacity"),
                        cast_shadow=bool(m.get("cast_shadow", True)),
                        cube_map=cube,
                        host_offset_copy=True if isinstance(copy, dict) else None,
                        host_offset_twin=copy.get("twin") if isinstance(copy, dict) else None,
                    ),
                }
            )
        bump(counts, kind + "_placements")

    chars_dir = characters_dir(root) if characters else None
    turns = {}
    for c in doc.get("characters") or []:
        bump(counts, "character_placements")
        if not characters:
            bump(skipped, "characters")
            continue
        off = not c.get("enabled", True)
        if off and not disabled:
            bump(skipped, "characters_disabled")
            continue
        kind_id = str((c.get("character_type") or {}).get("value"))
        ch = character_choice(doc, c, chars_dir, turns.get(kind_id, 0))
        if ch["pick"] == "candidate_in_turn":
            turns[kind_id] = turns.get(kind_id, 0) + 1
        if ch["glb"] is None:
            bump(missing, "character GLB of %s" % (ch["character"] or c.get("name") or "?"))
        loc, quat = placement_trs(c, CHARACTER_PIVOT_HEIGHT if ch["glb"] else 0.0)
        uid = c.get("uid") or ""
        group = ("Disabled",) if off else ("Characters", ch["character"] or "unknown")
        plan["instances"].append(
            {
                "kind": "character",
                "group": group,
                "name": object_name(ch["variant"] or ch["character"] or "character", uid),
                "glb": ch["glb"],
                "loc": loc,
                "quat": quat,
                "character": True,
                "outfit": ch["outfit"],
                "props": _props(
                    level=name,
                    kind="character",
                    uid=uid,
                    node_id=c.get("id") or uid.split(":", 1)[-1],
                    fragment=c.get("fragment"),
                    path=c.get("path"),
                    node_name=c.get("name"),
                    group=(c.get("group") or {}).get("name"),
                    character=ch["character"],
                    character_type=(c.get("character_type") or {}).get("name"),
                    variant=ch["variant"],
                    variant_pick=ch["pick"],
                    variant_member=ch["member"],
                    outfit=ch["outfit"] if ch["glb"] else None,
                    variant_status=ch["status"],
                    variant_candidates=", ".join(ch["candidates"]),
                    state_of_mind=(c.get("state_of_mind") or {}).get("name"),
                    weapon_type=(c.get("weapon_type") or {}).get("name"),
                    enabled=bool(c.get("enabled", True)),
                    pivot_height=CHARACTER_PIVOT_HEIGHT if ch["glb"] else None,
                ),
            }
        )
        bump(counts, "characters")

    if nav:
        p = nav_glb(root, name)
        if os.path.isfile(p):
            plan["nav"] = p
        elif (doc.get("nav") or doc.get("path_objects")) and name:
            bump(skipped, "nav_glb_not_in_export")
    counts["instances"] = len(plan["instances"])
    counts["distinct_glbs"] = len({i["glb"] for i in plan["instances"] if i["glb"]})
    return plan


# --------------------------------------------------------------------------------------
# Blender side
# --------------------------------------------------------------------------------------

try:
    import bpy
except ImportError:  # the functions above work without Blender
    bpy = None


def _log(msg):
    print("[watchmen level] " + msg)
    sys.stdout.flush()


def _child_collection(parent, name):
    coll = bpy.data.collections.new(name[:63])
    parent.children.link(coll)
    return coll


def _layer_collection(layer, coll):
    if layer.collection == coll:
        return layer
    for ch in layer.children:
        hit = _layer_collection(ch, coll)
        if hit is not None:
            return hit
    return None


def _exclude(context, coll):
    """Switch a collection off in every view layer of the scene (its instances still
    show)."""
    for vl in context.scene.view_layers:
        lc = _layer_collection(vl.layer_collection, coll)
        if lc is not None:
            lc.exclude = True


def _import_glb(context, path):
    """Import one GLB with Blender's glTF importer; the objects it created and linked
    into a collection (an importer of Blender 4.2 and later also makes an unlinked object
    for the bone shape, which is left where it is)."""
    before = set(bpy.data.objects.keys())
    colls = set(bpy.data.collections.keys())
    context.view_layer.active_layer_collection = context.view_layer.layer_collection
    kw = {}
    if "disable_bone_shape" in bpy.ops.import_scene.gltf.get_rna_type().properties.keys():
        kw["disable_bone_shape"] = True
    try:
        res = bpy.ops.import_scene.gltf(filepath=path, **kw)
    except RuntimeError as e:  # how bpy.ops raises an operator's error report
        raise LevelError(
            "Blender's glTF importer failed on %s: %s" % (path, str(e).strip())
        ) from None
    if "FINISHED" not in res:
        raise LevelError("Blender's glTF importer did not finish on %s" % path)
    new = [o for o in bpy.data.objects if o.name not in before and o.users_collection]
    made = [c for c in bpy.data.collections if c.name not in colls]
    return new, made


def _move(objs, coll):
    for o in objs:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)


def _drop_empty(colls):
    for c in colls:
        try:
            if not c.all_objects:
                bpy.data.collections.remove(c)
        except ReferenceError:
            pass


def _library_collection(
    context, lib_root, path, cache, frame, tmpdir, character=False, outfit=1, docs=None
):
    """The collection that holds the objects of one GLB (for a character: of one outfit of
    it), imported on first use.  `docs` keeps the JSON of the character GLBs read so far."""
    key = (path, bool(character), outfit if character else 1)
    if key in cache:
        return cache[key]
    doc = docs.get(path) if docs is not None else None
    if doc is None:
        doc = glb_json(path)
        if character and docs is not None:
            docs[path] = doc
    if character and outfit != 1 and outfit_swap(doc, outfit) is None:
        # the file has no nodes of its own for that outfit: the outfit it shows
        cache[key] = _library_collection(
            context, lib_root, path, cache, frame, tmpdir, True, 1, docs
        )
        return cache[key]
    got = glb_frame(doc)
    if got != frame:
        raise LevelError(
            "%s is in the %s frame and the level file in the %s frame: true-frame GLBs "
            "need a true-frame level file (export both with the same --frame)" % (path, got, frame)
        )
    src, clip = path, None
    if character:
        clip = pick_idle([a.get("name") for a in doc.get("animations") or []])
        src = os.path.join(tmpdir, "character_%d.glb" % len(cache))
        write_glb(src, prune_gltf(doc, clip, outfit), path)
    objs, made = _import_glb(context, src)
    if character:
        try:
            os.remove(src)
        except OSError:
            pass
    label = ("CHR " if character else "LIB ") + _stem(path)
    if character and outfit != 1:
        label = "%s outfit %d" % (label[:50], outfit)
    coll = _child_collection(lib_root, label)
    _move(objs, coll)
    _drop_empty(made)
    coll["watchmen_glb"] = path
    if character:
        coll["watchmen_outfit"] = outfit
    if clip:
        coll["watchmen_pose_clip"] = clip
    cache[key] = coll
    return coll


def _socket(sockets, *names):
    for n in names:
        for s in sockets:
            if s.identifier == n or s.name == n:
                return s
    return None


def _terrain_material(name, png):
    """A plain material for a terrain layer: its texture times the vertex tint, or grey
    times the tint when the export has no PNG for it."""
    mat = bpy.data.materials.new(name[:63])
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        return mat
    rough = _socket(bsdf.inputs, "Roughness")
    if rough is not None:
        rough.default_value = 1.0
    spec = _socket(bsdf.inputs, "Specular IOR Level", "Specular")
    if spec is not None:
        spec.default_value = 0.0
    base = _socket(bsdf.inputs, "Base Color")
    tint = nt.nodes.new("ShaderNodeVertexColor")
    tint.location = (-500, 100)
    mix = nt.nodes.new("ShaderNodeMix")  # Blender 3.4 and later
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    fac = _socket(mix.inputs, "Factor_Float", "Factor")
    a = _socket(mix.inputs, "A_Color")
    b = _socket(mix.inputs, "B_Color")
    res = _socket(mix.outputs, "Result_Color")
    mix.location = (-250, 250)
    if fac is not None:
        fac.default_value = 1.0
    if png:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.location = (-600, 400)
        tex.image = bpy.data.images.load(png, check_existing=True)
        if tex.image.packed_file is None:
            tex.image.pack()  # the .blend must not point back into the export
        nt.links.new(tex.outputs[0], a)
    else:
        a.default_value = (0.35, 0.35, 0.35, 1.0)
    nt.links.new(tint.outputs[0], b)
    nt.links.new(res, base)
    return mat


def _add_terrain(context, plan, coll, frame, stats):
    for t in plan["terrain"]:
        path = t["glb"]
        if not os.path.isfile(path):
            _log("terrain GLB not found: %s" % path)
            continue
        doc = glb_json(path)
        if glb_frame(doc) != frame:
            raise LevelError("%s is not in the frame of the level file (%s)" % (path, frame))
        textures = {
            m.get("name"): (m.get("extras") or {}).get("texture")
            for m in doc.get("materials") or []
        }
        objs, made = _import_glb(context, path)
        _move(objs, coll)
        _drop_empty(made)
        holder = bpy.data.objects.new(("Terrain " + t["name"])[:63], None)
        holder.empty_display_size = 1.0
        holder.rotation_mode = "QUATERNION"
        holder.location = t["loc"]
        holder.rotation_quaternion = t["quat"]
        for k, v in t["props"].items():
            holder[k] = v
        coll.objects.link(holder)
        for o in objs:
            if o.parent is None:
                o.parent = holder
        cache = {}
        for o in objs:
            if o.type != "MESH":
                continue
            stats["terrain_objects"] = stats.get("terrain_objects", 0) + 1
            for slot in o.material_slots:
                old = slot.material
                base = re.sub(r"\.\d{3}$", "", old.name) if old else o.name
                if base not in cache:
                    tex = (old.get("texture") if old else None) or textures.get(base)
                    png = texture_png(plan["root"], tex) if tex else None
                    cache[base] = _terrain_material("Terrain " + base, png)
                    if tex:
                        cache[base]["watchmen_texture"] = tex
                    stats["terrain_layers"] = stats.get("terrain_layers", 0) + 1
                    if png:
                        stats["terrain_layers_textured"] = (
                            stats.get("terrain_layers_textured", 0) + 1
                        )
                slot.material = cache[base]
                if old is not None and old.users == 0:
                    bpy.data.materials.remove(old)
            if not o.material_slots:
                if None not in cache:
                    cache[None] = _terrain_material("Terrain", None)
                o.data.materials.append(cache[None])


def _dedupe_images(before, seen):
    """Give identical packed images (the same PNG embedded in several GLBs) one datablock.
    Returns (images removed, bytes of packed data removed).

    Called again and again while the library is built, so that the copies do not pile up:
    `before` (names of the images already looked at, updated here) and `seen` (key ->
    name of the image kept) carry over.  The key is the packed file's bytes, the colour
    space and the alpha mode; the image's pixels are never read (``Image.size`` would
    decode every image into memory)."""
    import hashlib

    dup = {}
    saved = 0
    for img in bpy.data.images:
        if img.name in before:
            continue
        pf = img.packed_file
        if pf is None or not pf.size:
            continue
        key = (
            pf.size,
            hashlib.sha1(pf.data).digest(),
            img.colorspace_settings.name,
            img.alpha_mode,
        )
        first = bpy.data.images.get(seen[key]) if key in seen else None
        if first is None:
            seen[key] = img.name
        else:
            dup[img] = first
            saved += pf.size
    if not dup:
        before.update(bpy.data.images.keys())
        return 0, 0
    trees = [m.node_tree for m in bpy.data.materials if m.node_tree is not None]
    trees.extend(bpy.data.node_groups)
    for tree in trees:
        for node in tree.nodes:
            img = getattr(node, "image", None)
            if img is not None and img in dup:
                node.image = dup[img]
    for img, first in dup.items():
        if img.users:  # used by something that is not a shader node
            img.user_remap(first)
    gone = list(dup)
    if hasattr(bpy.data, "batch_remove"):
        bpy.data.batch_remove(gone)
    else:
        for img in gone:
            bpy.data.images.remove(img)
    before.update(bpy.data.images.keys())
    return len(gone), saved


def _peak_memory_mb():
    """The process's peak resident memory in MB, or None where it cannot be read."""
    try:
        import resource
    except ImportError:  # Windows
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1048576.0 if sys.platform == "darwin" else 1024.0))


def _check_files(plan):
    """Read the header of every GLB the plan imports before anything is created: a file
    that is no GLB, or one in another frame than the level file, stops the import here."""
    frame = plan["frame"]
    paths = [t["glb"] for t in plan["terrain"] if os.path.isfile(t["glb"])]
    paths += sorted({i["glb"] for i in plan["instances"] if i["glb"]})
    if plan["nav"]:
        paths.append(plan["nav"])
    for path in paths:
        try:
            got = glb_frame(glb_json(path))
        except (ValueError, OSError) as e:
            raise LevelError("cannot read %s: %s" % (path, e)) from None
        if got != frame:
            raise LevelError(
                "%s is in the %s frame and the level file in the %s frame: true-frame GLBs "
                "need a true-frame level file (export both with the same --frame)"
                % (path, got, frame)
            )


def import_level(
    context,
    level_path,
    characters=True,
    sky=True,
    nav=True,
    disabled=False,
    limit=0,
    dedupe_images=True,
):
    """Import the level file `level_path` into the scene of `context`.  Returns the
    summary dict that is also stored as JSON in the level collection's ``watchmen_import``
    property."""
    import tempfile

    t0 = time.time()
    if getattr(context, "mode", "OBJECT") != "OBJECT":
        raise LevelError("switch to Object Mode before importing a level")
    doc = load_level(level_path)
    root = find_export_root(level_path)
    plan = build_plan(doc, root, level_path, characters, sky, nav, disabled, limit)
    frame, name = plan["frame"], plan["level"]
    _log(
        "%s: %d instances of %d GLBs, frame %s, export %s"
        % (name, len(plan["instances"]), plan["counts"]["distinct_glbs"], frame, root)
    )
    if frame == FRAME_MIRRORED:
        _log(
            "the level file has no coordinate_frame key (--frame mirrored): the level "
            "will stand as a mirror image of the game"
        )
    here = os.path.abspath(level_path)
    for c in bpy.data.collections:
        if c.get("watchmen_level_file") == here:
            raise LevelError(
                "%s is already in this file (collection %r); delete that collection with "
                "everything in it before importing the level again" % (name, c.name)
            )
    _check_files(plan)
    _log("files checked, %.1f s" % (time.time() - t0))
    scene = context.scene
    keep = (scene.frame_start, scene.frame_end, scene.frame_current, scene.render.fps)
    active = context.view_layer.active_layer_collection.collection
    images_before = set(bpy.data.images.keys())
    images_seen = {}
    removed = saved = 0
    top = _child_collection(scene.collection, name)
    top["watchmen_level_file"] = here
    lib_root = _child_collection(top, name + " Library")
    groups = {}

    def group(path):
        if path not in groups:
            parent = top if len(path) == 1 else group(path[:-1])
            label = (name + " " + path[0]) if len(path) == 1 else path[-1]
            groups[path] = _child_collection(parent, label)
        return groups[path]

    for first in ("Terrain", "Props", "Characters", "Sky"):
        if first == "Terrain" or any(i["group"][0] == first for i in plan["instances"]):
            group((first,))
    stats = {}
    wm = context.window_manager
    tmpdir = tempfile.mkdtemp(prefix="watchmen_level_")
    cache = {}
    docs = {}

    def lib_key(inst):
        return (inst["glb"], bool(inst.get("character")), inst.get("outfit") or 1)

    try:
        _add_terrain(context, plan, group(("Terrain",)), frame, stats)
        _log("terrain: %d objects, %.1f s" % (stats.get("terrain_objects", 0), time.time() - t0))
        todo = []
        known = set()
        for inst in plan["instances"]:
            key = lib_key(inst)
            if inst["glb"] and key not in known:
                known.add(key)
                todo.append(key)
        wm.progress_begin(0, max(1, len(todo)))
        for n, (path, is_char, outfit) in enumerate(todo):
            _library_collection(
                context, lib_root, path, cache, frame, tmpdir, is_char, outfit, docs
            )
            wm.progress_update(n + 1)
            if dedupe_images and ((n + 1) % DEDUPE_EVERY == 0 or n + 1 == len(todo)):
                got = _dedupe_images(images_before, images_seen)
                removed, saved = removed + got[0], saved + got[1]
            if (n + 1) % 25 == 0 or n + 1 == len(todo) or is_char:
                _log(
                    "library %d / %d  %.1f s  %s%s"
                    % (
                        n + 1,
                        len(todo),
                        time.time() - t0,
                        _stem(path),
                        " outfit %d" % outfit if is_char and outfit != 1 else "",
                    )
                )
        docs.clear()
        wm.progress_end()
        made = {}
        for inst in plan["instances"]:
            obj = bpy.data.objects.new(inst["name"], None)
            obj.rotation_mode = "QUATERNION"
            obj.location = inst["loc"]
            obj.rotation_quaternion = inst["quat"]
            if inst["glb"]:
                obj.instance_type = "COLLECTION"
                obj.instance_collection = cache[lib_key(inst)]
                obj.empty_display_size = 0.25
            else:
                obj.empty_display_type = "CUBE"
                obj.empty_display_size = 0.5
                obj["watchmen_missing"] = True
            for k, v in inst["props"].items():
                obj[k] = v
            if inst["glb"]:
                obj["watchmen_glb"] = inst["glb"]
            if inst["kind"] == "sky":
                # a sky dome encloses the level: seen by the camera, but it must not shadow
                # the lights a user adds outside it
                for flag in ("visible_shadow", "visible_diffuse", "visible_glossy"):
                    if hasattr(obj, flag):
                        setattr(obj, flag, False)
            group(inst["group"]).objects.link(obj)
            made[inst["kind"]] = made.get(inst["kind"], 0) + 1
        _log("placed %d instances, %.1f s" % (len(plan["instances"]), time.time() - t0))
        if plan["nav"]:
            ndoc = glb_json(plan["nav"])
            if glb_frame(ndoc) != frame:
                raise LevelError("%s is not in the frame of the level file" % plan["nav"])
            objs, colls = _import_glb(context, plan["nav"])
            _move(objs, group(("Navigation",)))
            _drop_empty(colls)
            stats["nav_objects"] = len(objs)
            _log("navigation mesh: %d objects, %.1f s" % (len(objs), time.time() - t0))
        if dedupe_images:
            got = _dedupe_images(images_before, images_seen)
            removed, saved = removed + got[0], saved + got[1]
            _log(
                "merged %d identical images (%.1f MB), %.1f s"
                % (removed, saved / 1e6, time.time() - t0)
            )
    except Exception:
        # what was built so far stays, but not in view: library objects lie at the origin
        _exclude(context, lib_root)
        _log(
            "the import failed: the partial level is left in the collection %r with its "
            "Library switched off; delete it before importing again" % top.name
        )
        raise
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        scene.frame_start, scene.frame_end, scene.render.fps = keep[0], keep[1], keep[3]
        scene.frame_set(keep[2])
        lc = _layer_collection(context.view_layer.layer_collection, active)
        if lc is not None and not lc.exclude:
            context.view_layer.active_layer_collection = lc
    _exclude(context, lib_root)
    for off in (("Navigation",), ("Characters", "Scene models"), HOST_OFFSET_GROUP):
        if off in groups:
            _exclude(context, groups[off])
    far = 0.0
    if context.screen is not None:
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                for sp in area.spaces:
                    if sp.type == "VIEW_3D" and sp.clip_end < 10000.0:
                        sp.clip_end = far = 10000.0
    summary = {
        "level": name,
        "level_file": os.path.abspath(level_path),
        "export": root,
        "frame": frame,
        "blender": bpy.app.version_string,
        "seconds": round(time.time() - t0, 1),
        "counts": plan["counts"],
        "instances_made": made,
        "library_collections": len({c.name for c in cache.values()}),
        "peak_memory_mb": _peak_memory_mb(),
        "skipped": plan["skipped"],
        "missing": plan["missing"],
        "pose_clips": {
            _stem(p): c.get("watchmen_pose_clip", "") for (p, ch, _o), c in cache.items() if ch
        },
        "images_merged": removed,
        "image_bytes_merged": saved,
        "viewport_clip_end_set": far,
    }
    summary.update(stats)
    top["watchmen_import"] = json.dumps(summary, sort_keys=True)
    _log("done in %.1f s: %s" % (summary["seconds"], json.dumps(made, sort_keys=True)))
    if plan["skipped"]:
        _log("left out: %s" % json.dumps(plan["skipped"], sort_keys=True))
    if plan["missing"]:
        _log("%d files not found, e.g. %s" % (len(plan["missing"]), sorted(plan["missing"])[0]))
    return summary


if bpy is not None:
    from bpy.props import BoolProperty, IntProperty, StringProperty
    from bpy_extras.io_utils import ImportHelper

    class IMPORT_SCENE_OT_watchmen_level(bpy.types.Operator, ImportHelper):
        """Import a watchmen <Level>.level.json: instanced models, terrain, sky, characters"""

        bl_idname = "import_scene.watchmen_level"
        bl_label = "Import Watchmen level"
        bl_options = {"REGISTER", "UNDO"}

        filename_ext = ".json"
        # The properties as a plain dict: Blender reads the class's own __annotations__
        # entry.  Written as ordinary annotations, their string arguments are read by
        # pyflakes as forward references.
        __annotations__ = {
            "filter_glob": StringProperty(default="*.level.json;*.json", options={"HIDDEN"}),
            "use_characters": BoolProperty(
                name="Characters",
                description="Place the character GLB of every placed character, idle pose",
                default=True,
            ),
            "use_sky": BoolProperty(name="Sky", description="Place the sky models", default=True),
            "use_nav": BoolProperty(
                name="Navigation mesh",
                description="Import <Level>.nav.glb into a switched-off collection",
                default=True,
            ),
            "use_disabled": BoolProperty(
                name="Disabled and invisible placements",
                description="Also place what the level file marks as disabled or invisible",
                default=False,
            ),
            "limit": IntProperty(
                name="Limit",
                description="Place only the first N model placements (0: all)",
                default=0,
                min=0,
            ),
            "use_dedupe": BoolProperty(
                name="Merge identical images",
                description="Keep one image for a texture that several GLBs embed",
                default=True,
            ),
        }

        def execute(self, context):
            try:
                s = import_level(
                    context,
                    self.filepath,
                    characters=self.use_characters,
                    sky=self.use_sky,
                    nav=self.use_nav,
                    disabled=self.use_disabled,
                    limit=self.limit,
                    dedupe_images=self.use_dedupe,
                )
            except (LevelError, OSError, ValueError) as e:
                self.report({"ERROR"}, str(e))
                return {"CANCELLED"}
            if s["frame"] == FRAME_MIRRORED:
                self.report(
                    {"WARNING"},
                    "mirrored frame (the level file has no coordinate_frame key): the level "
                    "is a mirror image of the game",
                )
            self.report(
                {"INFO"},
                "%s: %d instances of %d GLBs in %.0f s"
                % (s["level"], s["counts"]["instances"], s["library_collections"], s["seconds"]),
            )
            return {"FINISHED"}

    def _menu(self, context):
        self.layout.operator(
            IMPORT_SCENE_OT_watchmen_level.bl_idname, text="Watchmen level (.level.json)"
        )

    def register():
        if not hasattr(bpy.types, "IMPORT_SCENE_OT_watchmen_level"):
            bpy.utils.register_class(IMPORT_SCENE_OT_watchmen_level)
            bpy.types.TOPBAR_MT_file_import.append(_menu)

    def unregister():
        if hasattr(bpy.types, "IMPORT_SCENE_OT_watchmen_level"):
            bpy.types.TOPBAR_MT_file_import.remove(_menu)
            bpy.utils.unregister_class(IMPORT_SCENE_OT_watchmen_level)


def parse_args(argv):
    import argparse

    ap = argparse.ArgumentParser(
        prog="blender -b --python blender_import_level.py --",
        description="Import a watchmen <Level>.level.json into Blender.",
    )
    ap.add_argument("level", nargs="?", help="<export>/levels/<Level>.level.json")
    ap.add_argument("--save", metavar="OUT.blend", help="save the scene to this file")
    ap.add_argument("--no-characters", action="store_true", help="leave the characters out")
    ap.add_argument("--no-sky", action="store_true", help="leave the sky models out")
    ap.add_argument("--no-nav", action="store_true", help="leave the navigation mesh out")
    ap.add_argument(
        "--include-disabled",
        action="store_true",
        help="also place what the level file marks as disabled or invisible",
    )
    ap.add_argument("--limit", type=int, default=0, metavar="N", help="first N model placements")
    ap.add_argument(
        "--keep-duplicate-images",
        action="store_true",
        help="do not merge identical images embedded in several GLBs",
    )
    ap.add_argument("--compress", action="store_true", help="compress the saved .blend")
    return ap.parse_args(argv)


def main(argv):
    """Command line: with a level file import it (and save); without one, inside Blender,
    register the operator and open its file browser.  Without Blender, print the plan."""
    args = parse_args(argv)
    if bpy is None:
        if not args.level:
            print(__doc__)
            return 0
        doc = load_level(args.level)
        plan = build_plan(
            doc,
            find_export_root(args.level),
            args.level,
            not args.no_characters,
            not args.no_sky,
            not args.no_nav,
            args.include_disabled,
            args.limit,
        )
        out = {k: plan[k] for k in ("level", "frame", "root", "counts", "skipped", "missing")}
        print(json.dumps(out, indent=1, sort_keys=True))
        return 0
    register()
    if not args.level:
        if not bpy.app.background:
            bpy.ops.import_scene.watchmen_level("INVOKE_DEFAULT")
        return 0
    if (
        bpy.app.background
        and not bpy.data.filepath
        and sorted(o.name for o in bpy.data.objects) == ["Camera", "Cube", "Light"]
    ):
        bpy.data.objects.remove(bpy.data.objects["Cube"])  # the start-up cube, at the origin
    try:
        import_level(
            bpy.context,
            args.level,
            characters=not args.no_characters,
            sky=not args.no_sky,
            nav=not args.no_nav,
            disabled=args.include_disabled,
            limit=args.limit,
            dedupe_images=not args.keep_duplicate_images,
        )
    except (LevelError, OSError, ValueError) as e:
        _log("error: %s" % e)
        return 1
    if args.save:
        out = os.path.abspath(args.save)
        bpy.ops.wm.save_as_mainfile(filepath=out, compress=bool(args.compress))
        _log("saved %s (%.1f MB)" % (out, os.path.getsize(out) / 1e6))
    return 0


if __name__ == "__main__":
    _argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if bpy is None or (
        "--" not in sys.argv and os.path.abspath(sys.argv[0]) == os.path.abspath(__file__)
    ):
        # plain Python (with or without the bpy module): the arguments follow the script
        _argv = sys.argv[1:]
    _rc = main(_argv)
    if _rc and (bpy is None or bpy.app.background):
        sys.exit(_rc)
