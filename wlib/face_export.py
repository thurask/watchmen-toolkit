#!/usr/bin/env python3
"""face_export.py -- cutscene-head glbs (face-POSE libraries) from the
ENGINE-EXACT face binds.

FINDING (2026-07-08j): every FACE clip is 100%% type-3 (constant) tracks --
the game has NO keyframed facial animation; faces are a library of expression
POSES (MouthTalk/MouthClosed/EyesAnger/...) blended procedurally at runtime
(audio-driven talk, blinks).  Each glb therefore carries 24 named poses as
2-frame hold animations.

Every face-rigged head (standard 19-node rig: Jaw/UpperLip/LowerLip/eyebrows/
EyeLid/cheeks/eyes/mouth-sides under Bip01>Neck>Head) gets its bind built
straight from its own ModelRes node array (build_bind_file recipe) and every
FACE clip baked onto it (BS2/EN1/NTO FACE dirs; rig is shared, per-head node
locals differ slightly so bakes are per-head).

Replaces the old empirical face_glb.py (skin-cluster centroid bind + neutral
-clip rest).
"""

import os, sys, glob
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)  # append, never insert(0): flat module names must not shadow the stdlib


def find_heads(extract_out):
    """Every Jaw-rigged model in the archive.  Full art/characters tree scan
    (2026-07-09: the old common/models/head glob missed NiteOwl_Mask2/
    NiteOwl_MaskDry2 -- NiteOwl's 'head' is his cowl, mouth-only rig, no
    eye/brow bones -- plus GimpHead1-3 and Heavies_Head_1)."""
    ex = os.path.join(extract_out, "extracted")
    from parse_model_nodes import parse

    heads = []
    cands = []
    for dp, _, fns in os.walk(os.path.join(ex, "art", "characters")):
        cands += [os.path.join(dp, f) for f in fns if f.endswith(".model")]
    for m in sorted(cands):
        try:
            names, _, _, _ = parse(open(m, "rb").read())
        except Exception:
            continue
        if "Jaw" in names and "LowerLip" in names:
            heads.append(m[:-6])
    return heads


def face_clips(extract_out):
    out = {}
    for d in glob.glob(os.path.join(extract_out, "extracted", "Animation", "*", "FACE")):
        pref = d.split(os.sep)[-2]
        for f in glob.glob(os.path.join(d, "*.animation")):
            out["%s/%s" % (pref, os.path.basename(f)[:-10])] = f
    return out


# head -> FACE-clip family.  BS2 poses serve the female-skeleton family
# (BS2 + EN4 -- there is no EN4/FACE dir); EN1 poses serve the male
# Medium/Large/Small family (incl. GimpHead1-3 / Heavies_Head_1 -- no
# EN2/FACE dir exists); NTO = NiteOwl's masks (NiteOwl_Mask2/MaskDry2: the 4
# NTO poses track exactly their 17-node mouth-only rig).
def head_family(head):
    h = head.lower()
    if "female" in h or "twilight" in h:
        return "BS2"
    if "niteowl" in h or "nightowl" in h or "owl" in h:
        return "NTO"
    return "EN1"


def export(extract_out, outdir, budget=None):
    import bake_v4, char_lib, variant_glb as vg, build_bind_file as bbf

    clips = face_clips(extract_out)
    print(len(clips), "face clips")
    texroots = [os.path.join(extract_out, "textures")]
    bdir = os.path.join(extract_out, "binds", "face")
    os.makedirs(bdir, exist_ok=True)
    os.makedirs(outdir, exist_ok=True)
    import time

    t0 = time.time()
    for mbase in find_heads(extract_out):
        head = os.path.basename(mbase)
        out = os.path.join(outdir, head + ".glb")
        if os.path.exists(out):
            continue
        if budget and time.time() - t0 > budget:
            print("budget reached -- rerun to continue")
            return 1
        bind = os.path.join(bdir, "bind_face_%s.npz" % head)
        if not os.path.exists(bind):
            bbf.build(mbase + ".model", None, bind)
        bake_v4._load_bind(bind)
        bake_v4._bank_lookup = lambda nm: open(clips[nm], "rb").read() if nm in clips else None
        fam = head_family(head)
        anims = []
        for nm in sorted(clips):
            if not nm.startswith(fam + "/"):
                continue
            try:
                pal, dur = bake_v4.bake(nm, 2)
                if len(pal) == 1:  # FACE clips are static POSES (all t3
                    import numpy as _np  # tracks); hold 2 frames for viewers

                    pal = _np.repeat(pal, 2, axis=0)
                fps = 2.0 if len(pal) <= 3 else bake_v4.fps_for(len(pal), dur)  # header-exact
                anims.append((nm, pal, fps))
            except Exception as e:
                print("  bake fail %s %s: %s" % (head, nm, e))
        bv = np.load(bind, allow_pickle=True)
        bn = [str(x) for x in bv["names"]]
        parts = char_lib.load_parts([mbase], bn)
        tex = char_lib.find_textures(parts, texroots)
        vg.write_glb(parts, anims, out, bind, textures=tex)
    return 0
