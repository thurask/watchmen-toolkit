#!/usr/bin/env python3
"""Attach the clip metadata of a watchmen character GLB to the actions Blender imported.

Blender's glTF importer does not import ``animations[i].extras`` (checked: Blender 5.2.2,
io_scene_gltf2 5.2.40 -- ``set_extras`` is called for cameras, lights, materials, meshes,
nodes, bones and scenes, never for an animation), so the actions arrive under their clip
names without custom properties.  The metadata is still in the file: this script reads the
GLB's JSON chunk and sets ``action["watchmen"]`` on the action of the same name.

In Blender (Scripting workspace, after File > Import > glTF 2.0)::

    import sys; sys.path.insert(0, r"<toolkit>/tools")
    import blender_attach_extras
    blender_attach_extras.attach(r"<path>/Rorschach.glb")

or from a shell: ``blender --python tools/blender_attach_extras.py -- Rorschach.glb``
(the GLB is imported first when no action of the file is in the session).

JSON ``null`` cannot be stored in an ID property: a null member of an object is left out
and a null inside a list becomes ``""`` (the list keeps its length).

Outside Blender the module only reads: ``python3 blender_attach_extras.py FILE.glb`` prints
how many animations carry ``extras.watchmen``.
"""

import json
import struct
import sys


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


def clean(v):
    """`v` without JSON nulls, which an ID property cannot hold: a null member of an
    object is dropped, a null element of a list becomes ""."""
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items() if x is not None}
    if isinstance(v, list):
        return ["" if x is None else clean(x) for x in v]
    return v


def clip_extras(path, key="watchmen"):
    """{animation name: extras[key] without nulls} of every animation of the GLB that
    carries it (the synthesised GRIP poses carry none)."""
    out = {}
    for a in glb_json(path).get("animations") or []:
        ex = (a.get("extras") or {}).get(key)
        if ex is not None and a.get("name"):
            out[a["name"]] = clean(ex)
    return out


def attach(path, key="watchmen", actions=None):
    """Set action[key] on every action named like an animation of the GLB `path`.
    Returns (attached, [animation names without an action]).  `actions`: a mapping
    name -> action (default: bpy.data.actions)."""
    if actions is None:
        import bpy

        actions = bpy.data.actions
    done, missing = 0, []
    for name, ex in sorted(clip_extras(path, key).items()):
        act = actions.get(name)
        if act is None:
            missing.append(name)
            continue
        act[key] = ex
        done += 1
    return done, missing


def main(argv):
    args = argv[argv.index("--") + 1 :] if "--" in argv else argv[1:]
    if not args:
        print(__doc__)
        return 2
    try:
        import bpy
    except ImportError:
        bpy = None
    for path in args:
        ex = clip_extras(path)
        if bpy is None:
            print("%s: %d animations carry extras.watchmen" % (path, len(ex)))
            continue
        if ex and not any(n in bpy.data.actions for n in ex):
            bpy.ops.import_scene.gltf(filepath=path)
        done, missing = attach(path)
        print("%s: %d of %d actions got their metadata" % (path, done, len(ex)))
        if missing:
            print("  no action for: %s" % ", ".join(missing[:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
