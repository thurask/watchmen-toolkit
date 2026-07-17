#!/usr/bin/env python3
"""char_lib.py -- bake a textured, animated character-library GLB.

Everything file-only + engine-exact: bind from build_bind_file (conj-FK),
palettes from bake_v4 (conjugate clips, absolute root, fps=frames/(dur/3)),
diffuse textures embedded.  No worldG (engine applies no root-pitch:
claude/work_D/worldg_test.py).
"""

import os, sys, glob, struct
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _clip_bank(animroot):
    bank = {}
    for dp, dn, fn in os.walk(animroot):
        for f in fn:
            if f.endswith(".animation"):
                bank[f[:-10].strip()] = os.path.join(dp, f)
    return bank


_TEXIDX = {}


def _texdir(matname, root):
    idx = _TEXIDX.get(root)
    if idx is None:
        # 2026-07-13 perf: os.walk visits each dir once; the old recursive
        # glob('**/*.bmp') + isdir did ~11k redundant scandirs (2.2s -> ~0.2s).
        idx = {}
        for dp, dns, fns in os.walk(root):
            for dn in dns:
                if dn.endswith(".bmp"):
                    idx.setdefault(dn[:-4].lower(), os.path.join(dp, dn))
        _TEXIDX[root] = idx
    return idx.get(matname.lower().strip())


_LAYERCACHE = {}  # (matname,tuple(texroots),flip) -> layers (2026-07-13 perf:
# shared materials repeat across ~25 variants; the normal-map
# green-flip PNG re-encode was paid every time)


def _find_layers(matname, texroots, flip_normal_g=True):
    _ck = (matname, tuple(texroots), flip_normal_g)
    if _ck in _LAYERCACHE:
        _r = _LAYERCACHE[_ck]
        return dict(_r) if _r else _r  # None/{} = cached "no texture found"
    _r = _find_layers_uncached(matname, texroots, flip_normal_g)
    _LAYERCACHE[_ck] = dict(_r) if _r else _r
    return _r


def _find_layers_uncached(matname, texroots, flip_normal_g=True):
    """material name -> {'diffuse','normal','mr','spec': png bytes} (whatever exists).
    normal: engine ATI2 X/Y + reconstructed Z, converted D3D->glTF (green flip;
    set WATCHMEN_NORMALS=dx to keep DirectX orientation).
    mr: glTF occlusion/roughness/metallic from the render-verified roughnessGen.png."""
    import io

    for root in texroots:
        d = _texdir(matname, root)
        if d:
            out = {}

            def grab(pat):
                g = sorted(glob.glob(d + "/" + pat))
                return g[0] if g else None

            f = grab("*_diffuse_*.png")
            if f:
                out["diffuse"] = open(f, "rb").read()
                # DXT1 1-bit cutout alpha -> glTF MASK
                try:
                    from PIL import Image
                    import numpy as _np

                    im = Image.open(f)
                    if im.mode == "RGBA":
                        a = _np.asarray(im)[:, :, 3]
                        if (a < 128).any():
                            out["alphaMask"] = True
                except Exception:
                    pass
            f = grab("*_normal_*.png")
            if f:
                if flip_normal_g and os.environ.get("WATCHMEN_NORMALS", "gl") != "dx":
                    from PIL import Image

                    im = Image.open(f).convert("RGB")
                    r, g_, b = im.split()
                    from PIL import ImageChops

                    im = Image.merge("RGB", (r, ImageChops.invert(g_), b))
                    buf = io.BytesIO()
                    im.save(buf, "PNG")
                    out["normal"] = buf.getvalue()
                else:
                    out["normal"] = open(f, "rb").read()
            f = grab("roughnessGen.png")
            if f:
                from PIL import Image

                g_ = Image.open(f).convert("L")
                zero = Image.new("L", g_.size, 0)
                full = Image.new("L", g_.size, 255)
                im = Image.merge(
                    "RGB", (full, g_, zero)
                )  # R=occlusion(1) G=roughness B=metallic(0)
                buf = io.BytesIO()
                im.save(buf, "PNG")
                out["mr"] = buf.getvalue()
            f = grab("*_specMap_*.png")
            if f:
                from PIL import Image

                im = Image.open(f).convert("RGB")
                buf = io.BytesIO()
                im.save(buf, "PNG")
                out["spec"] = buf.getvalue()
            if out:
                return out
    return None


def load_parts(models, bn):
    """Decode skinned mesh parts for the given bind bone-name order.
    models: .model base paths (no extension).  Returns variant_glb parts list
    with engine-exact submesh->material mapping."""
    import watchmen_extract as we, extract_skeletons as es, rig_glb

    uslot = {n: i for i, n in enumerate(bn)}
    # 2026-07-13: 'BipNN '-prefix-insensitive fallback. Thug/Heavies models
    # say 'RUpArmTwist' where the medium bind says 'Bip02 RUpArmTwist';
    # KnotTop_Large says 'Bip01 Attach RHand' vs bind 'Attach RHand'.
    # A silently dropped MID-LIST name shifts the rotate-by-one palette and
    # mis-skins everything after it (user QA: medium arms+head, large arms).
    # Exact matches always win, so validated skeletons are unaffected.
    import re

    _canon = lambda n: re.sub(r"^Bip\d+\s+", "", n)
    ucanon = {}
    for i, n in enumerate(bn):
        c = _canon(n)
        if c not in uslot:
            ucanon.setdefault(c, i)

    def _slot(x):
        if x in uslot:
            return uslot[x]
        if x in ucanon:
            return ucanon[x]
        c = _canon(x)
        if c in uslot:
            return uslot[c]
        return ucanon.get(c)

    parts = []
    for base in models:
        mh = open(base + ".model", "rb").read()
        ms = open(base + ".model.stream", "rb").read()
        # byte order: console (X360/PS3) model headers/streams are big-endian.
        # Compare descriptor COUNTS -- a BE model can yield a stray false-positive
        # LE descriptor (X360 GimpBody: LE=1 vs BE=2), so "LE if non-empty" mis-
        # picked "<" and dropped that model's real submeshes (missing chest).
        order = (
            ">" if len(we.find_descriptors(mh, ">")) > len(we.find_descriptors(mh, "<")) else "<"
        )
        be = order == ">"
        plist = [x for _, x in es._ordered_names(mh, order)]
        pf = [x for x in plist if _slot(x) is not None]
        ppal = [pf[(k - 1) % len(pf)] for k in range(len(pf))]  # engine rotate-by-one
        remap = np.array([_slot(n) for n in ppal], dtype=np.int64)
        descs = we.find_descriptors(mh, order)
        mats = we.extract_materials(mh)
        smat = we.submesh_materials(mh, order)
        off = 0
        for si_, (nv, stride, ib) in enumerate(descs):
            hi = len(ms) - nv * stride - ib
            c = off
            vbo = None
            while c <= min(off + 65536, hi):
                # require a CLEAN index buffer too: a false-positive VB (X360
                # TwilightLadyHair / rorschachspots) sits ~4 bytes before the
                # real one, passes _vb_ok, but has a ~50% repeated-index IB.
                if (
                    we._sane(struct.unpack_from(order + "f", ms, c)[0])
                    and we._vb_ok(ms, c, nv, stride, ib, order)
                    and we._ib_ok(ms, c, nv, stride, ib, order)
                ):
                    vbo = c
                    break
                c += 1
            if vbo is None:
                continue
            v, _, uv = we._decode_sub(ms, vbo, nv, stride, be)
            skidx, skw = rig_glb.decode_skin(ms, vbo, nv, stride, order)
            ibo = vbo + nv * stride
            T = []
            for t in range(ib // 6):
                x, y, z = struct.unpack_from(order + "3H", ms, ibo + t * 6)
                if x < nv and y < nv and z < nv and len({x, y, z}) == 3:
                    T.append((x, y, z))
            off = ibo + ib
            if not v or not T:
                continue
            SI = remap[np.clip(np.asarray(skidx, int), 0, len(remap) - 1)]
            parts.append(
                (
                    np.array(v, float),
                    SI.astype(np.uint16),
                    np.asarray(skw, np.float32),
                    np.array(T),
                    np.array(uv if uv else [(0.0, 0.0)] * len(v), np.float32),
                    (
                        mats[smat[si_][1]]
                        if si_ < len(smat) and smat[si_][1] < len(mats)
                        else (mats[si_] if si_ < len(mats) else "sub%d" % si_)
                    ),
                )
            )
    return parts


def find_textures(parts, texroots):
    """material name -> layer dict for every part material."""
    tex = {}
    for pt in parts:
        nm = pt[5]
        if nm not in tex:
            layers = _find_layers(nm, texroots)
            if layers:
                tex[nm] = layers
    return tex


def build_lib(bind, models, clips, out, animroot, texroots=(), upsample=2):
    """bind: npz path; models: iterable of .model base paths (no extension);
    clips: iterable of clip names; out: .glb path; animroot: extracted
    Animation dir; texroots: texture trees (<root>/**/<mat>.bmp/*_diffuse_*.png)."""
    sys.argv = ["bake", "--bind", bind, "--conj"]
    import importlib, bake_v4

    importlib.reload(bake_v4)
    import variant_glb as vg

    bank = _clip_bank(animroot)
    bake_v4._bank_lookup = lambda nm: open(bank[nm], "rb").read() if nm in bank else None
    bv = np.load(bind, allow_pickle=True)
    bn = [str(x) for x in bv["names"]]
    parts = load_parts(models, bn)
    print("parts:", len(parts))
    anims = []
    for clip in clips:
        p_, dur = bake_v4.bake(clip, upsample)
        fps = bake_v4.fps_for(len(p_), dur)  # header-exact (work_E/ENGINE_CONSTANTS.md)
        anims.append((clip, p_, fps))
    tex = {}
    for pt in parts:
        nm = pt[5]
        if nm not in tex:
            layers = _find_layers(nm, texroots)
            if layers:
                tex[nm] = layers
    vg.write_glb(parts, anims, out, bind, textures=tex)
    return out


# canonical library definitions (model paths relative to <extract_out>/extracted)
LIBS = {
    "Gimp2": dict(
        bind="gimp",
        models=[
            "art/characters/gimps/models/" + m
            for m in ("GimpBody", "GimpLegs1", "Straps1", "PvcShirt", "GimpHead3_NoSKL")
        ],
        clips=[
            "EN2_COM_MOV_idle_fidget_J",
            "EN2_COM_MOV_idle_fidget_hurt_back",
            "EN2_COM_MOV_idle_fidget_hurt_leg_right",
            "EN2_COM_MOV_strafe_left",
            "EN2_COM_DMG_stun_body_back",
            "EN2_COM_WPN_2H_heavy_NTO",
            "EN2_COM_ATT_freight_train",
        ],
    ),
    "Rorschach": dict(
        bind="rsh",
        models=["art/characters/rorschach/models/Rorschach"],
        clips=[
            "RSH_EXP_MOV_idle_fidget_A",
            "RSH_COM_MOV_jog_cycle",
            "RSH_EXP_MOV_walk_cycle",
            "RSH_COM_ATT_kick",
        ],
    ),
    "Dominatrix": dict(
        bind="female",
        models=[
            "art/characters/dominatrix/model/" + m
            for m in (
                "Dominatrix_Suits1",
                "Girl_Head_White",
                "Dominatrix_Boots2",
                "Dominatrix_Glove1",
            )
        ],
        clips=[
            "EN4_COM_MOV_run_cycle",
            "EN4_EXP_MOV_idle_fidget_A",
            "EN4_EXP_MOV_dance_cage_large_B",
            "EN4_COM_MOV_idle_gesture_B",
        ],
    ),
}


def build_all(extract_out, binds, outdir):
    """extract_out: watchmen.py-extract output dir; binds: {key: npz} from
    ensure_binds; outdir: where the glbs go."""
    os.makedirs(outdir, exist_ok=True)
    ex = os.path.join(extract_out, "extracted")
    done = []
    for name, spec in LIBS.items():
        models = [os.path.join(ex, m) for m in spec["models"]]
        missing = [m for m in models if not os.path.exists(m + ".model")]
        if missing:
            print("  ! %s: missing models %s -- skipped" % (name, missing))
            continue
        out = os.path.join(outdir, "CHAR_%s_LIB.glb" % name)
        build_lib(
            binds[spec["bind"]],
            models,
            spec["clips"],
            out,
            animroot=os.path.join(ex, "Animation"),
            texroots=[os.path.join(extract_out, "textures")],
        )
        print("  wrote", out)
        done.append(out)
    return done
