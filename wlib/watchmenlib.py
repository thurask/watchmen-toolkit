#!/usr/bin/env python3
"""watchmenlib -- one import for everything this project has reverse-engineered.

Facade over the battle-tested modules in wlib/ (each remains the
authority for its domain; this module only organizes access). Works from a
fresh install: only game files + these modules + the solved-constant npz/pkl
files shipped next to them are needed.

Sections: archive / assets / fragments / anim / data (solved binds, key tables)

Quick start:
    import watchmenlib as wl
    j = wl.fragment_json_file('X.fragment')     # lossless fragment JSON
    wl.build_variant_glb('Gimp.fragment.json','Gimp2','out.glb')
"""

import os, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)  # append, never insert: must not shadow stdlib

import watchmen_extract as _we  # naz walk, block extract, model decode
import export_female_anims as _efa  # grab_blocks + clip helpers
import extract_skeletons as _es  # skeleton .model record parsing
import rig_glb as _rig  # skin indices/weights decode
import kapow_props as _kp  # property hash + prop-bag JSON
import kapow_json as _kj  # per-asset-type JSON emitters
import kapow_fragment as _kf  # LOSSLESS fragment parser (2026-07-07)

import bake_v4 as _bake_mod  # engine-exact clip -> palette baker
import variant_glb as _vg  # character-variant GLB builder

# ---- data: solved constants ------------------------------------------------
# 2026-07-08: binds are now FILE-ONLY + engine-exact, built straight from each
# skeleton's ModelRes node array (wlib/build_bind_file.py):
#   Rb = FK of the node quats CONJUGATED (palette gauge; == capture-solved v14b
#        to 0.00deg on all non-twist bones, and engine-exact on twists too),
#   tloc = verbatim node locals, tb = FK(Rb, tloc)  (palette joint invariant
#   med 0.0000 on female + gimp captures; rsh == v10 quality).
# Capture-solved binds (bind_v14b_final / bind_gimp_v9 / bind_rsh_v10) are kept
# as validation references only -- see docs/ENGINE_CONSTANTS.md.
# 2026-07-24: the old module-level BINDS table pointed at a developer-machine
# sibling directory that never shipped; post-install every entry resolved to a
# nonexistent path inside site-packages.  Build the binds instead -- one call,
# from the game files, engine-exact:
#     binds = wl.ensure_binds('game.naz', 'OUT/binds')   # {'female': path, ...}


def bind_from_skeleton_header(
    header_bytes_or_path, template_npz=None, out_npz="/tmp/bind_file.npz"
):
    """ENGINE-EXACT file-only bind from any skeleton/mesh ModelRes header."""
    import build_bind_file as _bbf, tempfile

    if isinstance(header_bytes_or_path, (bytes, bytearray)):
        import os as _os

        fd, pth = tempfile.mkstemp(suffix=".header")
        _os.write(fd, header_bytes_or_path)
        _os.close(fd)
        header_bytes_or_path = pth
    return _bbf.build(header_bytes_or_path, template_npz, out_npz)


FRAGMENT_KEYS = os.path.join(_HERE, "kapow_fragment_keys.pkl")


# ---- archive ----------------------------------------------------------------
def extract_all(naz, out, *extra):
    """Full asset extraction (files/textures/models/audio/JSON) from game.naz.
    Extra args are passed through to watchmen_extract (e.g. '--vgmstream-cli',
    '/path/to/vgmstream-cli' for console X360/PS3 audio -> wav)."""
    return _we.main([str(naz), "-o", str(out)] + [str(x) for x in extra])


_SKEL_ASSETS = {  # skeleton source per bind (block asset name endswith)
    "female": "Female_Skeleton.model",
    "gimp": "Large_Gimp_Skeleton.model",
    "medium": "Medium_Skeleton.model",
    "large": "/Large_Skeleton.model",
    "small": "Small_Skeleton.model",
    "rsh": "Rorschach_Dry.model",
    "nto": "NightOwl_No_MaskDry.model",
}


def ensure_binds(naz="game.naz", outdir=None, required=None, extract_dir=None):
    """FILE-ONLY bind bootstrap: build engine-exact binds straight from the naz
    (or a loose Part 1 directory) for whatever skeletons are present, and return
    ``{key: npz_path}`` for the binds that now exist on disk.

    ``extract_dir``: a watchmen.py-extract output dir. When given, binds are
    built from the skeleton .model headers already sitting in
    ``<extract_dir>/extracted`` -- the same header bytes the naz block would
    yield -- so a completed extract needs NO naz to make binds. The naz is only
    read for skeletons whose .model isn't on disk (last resort).

    Part 1 ships only 5 of the 7 skeletons (no Female_Skeleton / Large_Gimp_
    Skeleton -- those are the Part 2 bordello cast), so skeletons that aren't in
    the source are **warned, not fatal**.  Pass ``required=[keys]`` to force a
    hard error when specific skeletons are absent (e.g. a Part 2 caller that
    truly needs 'female')."""
    import build_bind_file as _bbf, tempfile, sys as _sys, glob as _glob

    if not outdir:
        raise ValueError(
            "ensure_binds(naz, outdir): outdir is required -- it is where the built "
            "bind npz files go, e.g. wl.ensure_binds('game.naz', 'OUT/binds')"
        )
    os.makedirs(outdir, exist_ok=True)
    want = {k: os.path.join(outdir, "bind_%s_file_v1.npz" % k) for k in _SKEL_ASSETS}
    have = {k: v for k, v in want.items() if os.path.exists(v)}
    missing = {k: v for k, v in want.items() if k not in have}
    # Prefer the skeleton .model headers already extracted to disk (no naz needed).
    if missing and extract_dir:
        exroot = os.path.join(extract_dir, "extracted")
        _mindex = {}
        for _p in _glob.glob(os.path.join(exroot, "**", "*.model"), recursive=True):
            _mindex.setdefault(os.path.basename(_p), _p)  # e.g. Female_Skeleton.model
        for k in list(missing):
            asset = os.path.basename(_SKEL_ASSETS[k])  # strip any leading '/'
            src = _mindex.get(asset)
            if src:
                _bbf.build(src, None, missing[k])
                have[k] = missing.pop(k)
    if missing:
        blocks = grab_blocks(naz)
        for bk, b in blocks.items():
            if "h" not in b or not missing:
                continue
            for e, h, st in extract_block(b["h"], b.get("s")):
                for k in list(missing):
                    if (e.name or "").endswith(_SKEL_ASSETS[k]):
                        fd, pth = tempfile.mkstemp(suffix=".header")
                        os.write(fd, h)
                        os.close(fd)
                        _bbf.build(pth, None, missing[k])
                        os.unlink(pth)
                        have[k] = missing.pop(k)
    if missing:
        print(
            "note: %d skeleton(s) not present in %s (expected for Part 1): %s"
            % (len(missing), naz, ", ".join(sorted(missing))),
            file=_sys.stderr,
        )
    absent_req = set(required or ()) - set(have)
    if absent_req:
        raise RuntimeError("required skeletons not found in %s: %s" % (naz, sorted(absent_req)))
    if not have:
        raise RuntimeError("no skeletons found in %s" % (naz,))
    return have


def grab_blocks(naz="game.naz"):
    return _efa.grab_blocks(naz)


def block_order(naz="game.naz"):
    """'<' little-endian (PC) / '>' big-endian (X360/PS3), auto-detected from the
    first real block header. Used to gate the PC-only rig pipeline off consoles."""
    for _stem, _hs in grab_blocks(naz).items():
        if "h" in _hs:
            return _we.detect_block_order(_hs["h"])
    return "<"


def extract_block(header, stream=None):
    return _we.extract_block(header, stream)


# ---- assets -----------------------------------------------------------------
def model_descriptors(mb):
    return _we.find_descriptors(mb)


def model_materials(mb):
    return _we.extract_materials(mb)


def model_bone_names(mb):
    return [n for _, n in _es._ordered_names(mb)]


def decode_skin(stream, vbo, nv, stride):
    return _rig.decode_skin(stream, vbo, nv, stride)


def skeleton_records(mb):
    import skeleton_records as _sr

    return _sr.parse(mb)


def palette_order(mb, bind_names):
    """Render palette slot order: bind-filtered mesh name list, rotate-by-one.
    Engine uploads first N-1 slots when the last (GamePivot) is unused."""
    pf = [n for n in model_bone_names(mb) if n in set(bind_names)]
    return [pf[(k - 1) % len(pf)] for k in range(len(pf))]


# ---- fragments --------------------------------------------------------------
def parse_fragment(data):
    return _kf.parse(data)


def fragment_json(data):
    return _kj.to_json(".fragment", data)


def fragment_json_file(path):
    return _kj.to_json(path.lower(), open(path, "rb").read())


def asset_json(nm, data):
    return _kj.to_json(nm, data)


def kapow_hash(name):
    return _kp.kapow_hash(name.upper())


# ---- anim ---------------------------------------------------------------------
def decode_clip(anim_bytes):
    return _bake_mod.walk(anim_bytes)


def bake(clipname, bind=None, upsample=2, bank=None):
    """Engine-exact palettes: conjugate convention, absolute root.

    bind: path to a bind npz, e.g. wl.ensure_binds(naz, outdir)['female'].
    Returns (palettes (F,NB,3,4), duration_s)."""
    return _bake_mod.bake(clipname, upsample, bind=bind, conj=True, bank=bank)


def build_variant_glb(fragment_json_path, variant, out_glb, **kw):
    return _vg.build(fragment_json_path, variant, out_glb, **kw)


def write_glb(parts, manifest, out, bind_npz):
    return _vg.write_glb(parts, manifest, out, bind_npz)


__all__ = [n for n in dir() if not n.startswith("_")]
