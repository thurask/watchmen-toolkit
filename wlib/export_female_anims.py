#!/usr/bin/env python3
"""
export_female_anims.py -- archive-walk shims and the skinned body-mesh helper,
kept for callers of 1.4.0.

  grab_blocks(naz)            every block in memory at once ({stem: {"h", "s"}})
  iter_blocks(naz, streams)   watchmen_extract.iter_blocks: one block at a time
  mesh_arrays(header, stream) a skinned model's pieces as one buffer, read
                              through mesh_loader like every character loader

Up to 1.4.0 this module was also a standalone exporter (``python
export_female_anims.py game.naz out.glb``: the Dominatrix body with female
clips).  Its clip decoder repeated bake_v4.walk with the same GamePivot scan, and
its GLB writer repeated variant_glb's; both were removed in 1.5.0 -- the character
GLBs with every clip are `watchmen characters` / `watchmen char`.
"""

import sys

import numpy as np

import watchmen_extract as we


def grab_blocks(naz):
    """{stem: {"h": header bytes, "s": stream bytes}} of every block of the
    archive, all in memory at once (kept for callers of 1.4.0; the toolkit's own
    walks use watchmen_extract.iter_blocks, which reads one block at a time)."""
    return dict(iter_blocks(naz))


def iter_blocks(naz, streams=True):
    """watchmen_extract.iter_blocks: (stem, {"h", "s"}) one block at a time."""
    return we.iter_blocks(naz, streams)


def mesh_arrays(mh, ms, name="body"):
    """The skinned body mesh as one buffer -> (V [(x, y, z)], SI (n,4) uint8 palette
    indices, SW (n,4) float32, T [(a, b, c)] whole-mesh indices, subs [(vertex base,
    vertex count, first triangle, triangle count)]).  The pieces come from
    mesh_loader.load_submeshes (the model header; the descriptor scan only as a
    logged fallback), as in every character loader; 1.4.0 had a scan of its own
    here, without the clean-index-buffer test and little-endian only."""
    import mesh_loader as ml

    pieces, _rep = ml.load_submeshes(mh, ms, name, attrs=False)
    V, SI, SW, T, subs = [], [], [], [], []
    for sb in pieces:
        si, sw = sb["skin"]
        if si is None:
            print("  ! %s sub%d: no skin, left out" % (name, sb["index"]))
            continue
        base = len(V)
        ts = len(T)
        T.extend((base + int(x), base + int(y), base + int(z)) for x, y, z in sb["T"])
        V.extend(map(tuple, sb["V"].tolist()))
        SI.append(si)
        SW.append(sw)
        subs.append((base, len(sb["V"]), ts, len(T) - ts))
    SI = np.concatenate(SI).astype(np.uint8) if SI else np.zeros((0, 4), np.uint8)
    SW = np.concatenate(SW).astype(np.float32) if SW else np.zeros((0, 4), np.float32)
    return V, SI, SW, T, subs


if __name__ == "__main__":
    sys.exit(
        "export_female_anims.py no longer exports GLBs (its clip decoder duplicated\n"
        "bake_v4.walk); use `watchmen characters EXTRACT_OUT OUT_DIR` or `watchmen char`."
    )
