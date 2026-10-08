#!/usr/bin/env python3
"""char_lib.py -- bake a textured, animated character-library GLB.

Everything file-only + engine-exact: bind from build_bind_file (conj-FK),
palettes from bake_v4 (conjugate clips, absolute root, fps=frames/(dur/3)),
diffuse textures embedded.  No worldG (engine applies no root-pitch:
docs/ENGINE_CONSTANTS.md).
"""

import os, sys, glob, struct
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)  # append, never insert(0): flat module names must not shadow the stdlib


def _read_bytes(path):
    """The file's bytes; the handle is closed before returning."""
    with open(path, "rb") as fh:
        return fh.read()


def _clip_bank(animroot):
    bank = {}
    for dp, dn, fn in os.walk(animroot):
        dn.sort()  # os.walk order is the file system's: keep the result independent of it
        for f in sorted(fn):
            if f.endswith(".animation"):
                bank[f[:-10].strip()] = os.path.join(dp, f)
    return bank


_TEXIDX = {}


def _texindex(root):
    """watchmen_extract.TextureIndex of one texture tree (cached)."""
    idx = _TEXIDX.get(root)
    if idx is None:
        import watchmen_extract as _we

        idx = _TEXIDX[root] = _we.build_texture_index(root, require_diffuse=False)
    return idx


def _texdir(matname, root):
    """Texture dir of a material in the tree `root`, or None.

    A material that comes from a model is a watchmen_extract.TexRef and carries the
    asset path the model stores; the engine loads exactly that asset, so that is the
    directory used ('head' exists in three folders).  Only a material without a path,
    or whose path is not in the tree, is looked up by bare name: deterministic (asset
    paths sorted, first wins) and reported when ambiguous -- never by the order the
    file system lists directories in."""
    d = _texindex(root).resolve(matname)
    return None if d is None else str(d)


_LAYERCACHE = {}  # (matname,tuple(texroots),flip) -> layers (2026-07-13 perf:
# shared materials repeat across ~25 variants; the normal-map
# green-flip PNG re-encode was paid every time)


def _find_layers(matname, texroots, flip_normal_g=True):
    # the path is part of the key: a TexRef equals the plain name it carries
    _ck = (str(matname), getattr(matname, "path", None), tuple(texroots), flip_normal_g)
    _ck += (os.environ.get("WATCHMEN_MATERIALS"), os.environ.get("WATCHMEN_MATERIAL_OPTS"))
    if _ck in _LAYERCACHE:
        _r = _LAYERCACHE[_ck]
        return dict(_r) if _r else _r  # None/{} = cached "no texture found"
    _r = _find_layers_uncached(matname, texroots, flip_normal_g)
    _LAYERCACHE[_ck] = dict(_r) if _r else _r
    return _r


SHEET_TAG = "#sheet="  # TexRef path suffix naming a texture sheet other than the first


def sheet_ref(ref, sheet_name):
    """`ref` (a TexRef) wearing the named sheet of its texture: same material name,
    path + '#sheet=<name>', so it is a material of its own."""
    import watchmen_extract as _we

    base = (getattr(ref, "path", None) or "").partition(SHEET_TAG)[0]
    if not base or not sheet_name:
        return ref
    return _we.TexRef(str(ref), base + SHEET_TAG + sheet_name)


def _sheet_table(texdir, root):
    """Every sheet of the texture carved to `texdir` (watchmen_extract.texture_sheets
    dicts): from its sheet.json when that lists them, else from the Texture header
    under <extract_out>/extracted (a tree carved before sheet.json held the table),
    else the one sheet an old sheet.json describes."""
    import watchmen_extract as _we

    js = _we.read_sheet_json(texdir)
    if js.get("sheets"):
        return js["sheets"]
    try:
        rel = os.path.relpath(texdir, root)
        hp = os.path.join(os.path.dirname(os.path.abspath(root)), "extracted", rel)
        with open(hp, "rb") as fh:
            hdr = fh.read()
        got = _we.texture_sheets(hdr, "<") or _we.texture_sheets(hdr, ">")
        if got:
            return got
    except (OSError, ValueError):
        pass
    return [js] if js else []


def _flat_roughness(exponent):
    """The 4x4 roughness image watchmen_extract._make_roughness writes for a texture
    without a specSize layer, for another sheet's specular exponent."""
    import io, math
    from PIL import Image

    rv = 1.0 - min(1.0, math.sqrt(2.0 / (float(exponent) + 2.0)))
    r = int(round(min(1.0, max(0.0, rv)) * 255.0))
    buf = io.BytesIO()
    Image.merge(
        "RGB", (Image.new("L", (4, 4), 255), Image.new("L", (4, 4), r), Image.new("L", (4, 4), 0))
    ).save(buf, "PNG")
    return buf.getvalue()


def _find_layers_uncached(matname, texroots, flip_normal_g=True):
    """material name -> {'diffuse','normal','mr','spec': png bytes} (whatever exists).
    The texture is the one at the material's own asset path when it has one (_texdir).
    A path ending '#sheet=<name>' (sheet_ref) selects that sheet of the texture
    instead of the first: its material switches, and the layers it takes from other
    textures (<layer>MapOverride).  The first sheet's overrides apply as well.
    normal: engine ATI2 X/Y + reconstructed Z, converted D3D->glTF (green flip;
    set WATCHMEN_NORMALS=dx to keep DirectX orientation).  The PNG must come from
    this version's texture extraction: before 1.4.0 the PC ATI2 layers were written
    with X and Y swapped (watchmen_extract.ati2_xy), and no flip repairs that.
    'sheet': the sheet in use (alpha threshold, normal-map power, blend ...), if known.
    mr: glTF occlusion/roughness/metallic from the render-verified roughnessGen.png."""
    import io
    import materials as _mt
    import watchmen_extract as _we

    engine = _mt.mode() == "engine"
    base, _, sname = (getattr(matname, "path", None) or "").partition(SHEET_TAG)
    ref = _we.TexRef(str(matname), base) if sname else matname
    for root in texroots:
        d = _texdir(ref, root)
        if d:
            out = {}
            try:
                sheets = _sheet_table(d, root)
            except Exception:
                sheets = []
            sheet = _we.select_sheet(sheets, sname or None)
            over = {}
            for layer, opath in sorted((sheet.get("overrides") or {}).items()):
                od = _texdir(_we.texture_ref(opath), root)
                if od:
                    over[layer] = od
                else:
                    print(
                        "  ! sheet %r of %s: %s layer %s not found"
                        % (sheet.get("name"), matname, layer, opath)
                    )

            def grab(pat, layer=None):
                g = sorted(glob.glob(over.get(layer, d) + "/" + pat))
                return g[0] if g else None

            f = grab("*_diffuse_*.png", "diffuse")
            if f:
                out["diffuse"] = _read_bytes(f)
                if engine:
                    # the Texture header's alpha flag, when the extract recorded it
                    # (sheet.json "textureHasAlpha"): the engine's alpha test follows it
                    _fl = _we.read_sheet_json(os.path.dirname(f)).get("textureHasAlpha")
                    if isinstance(_fl, bool):
                        out["texAlphaFlag"] = _fl
                # DXT1 1-bit cutout alpha -> glTF MASK
                try:
                    from PIL import Image
                    import numpy as _np

                    with Image.open(f) as im:  # an image that is not RGBA is never read
                        if im.mode == "RGBA":
                            a = _np.asarray(im)[:, :, 3]
                            if (a < 128).any():
                                out["alphaMask"] = True
                            if engine and (a < 255).any():
                                out["texAlpha"] = (
                                    True  # the engine alpha-tests it (materials.alpha)
                                )
                except Exception:
                    pass
            f = grab("*_normal_*.png", "normal")
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
                    out["normal"] = _read_bytes(f)
            f = None if engine else grab("roughnessGen.png")
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
                # roughnessGen.png was baked from the FIRST sheet's exponent; a flat
                # one (no specSize layer) is redone for another sheet's exponent
                e0, e1 = (sheets[0].get("specularSize") if sheets else None), sheet.get(
                    "specularSize"
                )
                if (
                    sheet is not (sheets[0] if sheets else None)
                    and e1 is not None
                    and e1 > 0
                    and e1 != e0
                    and g_.size == (4, 4)
                    and not grab("*_specSize_*.png", "specSize")
                ):
                    out["mr"] = _flat_roughness(e1)
            f = grab("*_specMap_*.png", "specMap")
            if f:
                from PIL import Image

                im = Image.open(f).convert("RGB")
                buf = io.BytesIO()
                im.save(buf, "PNG")
                out["spec"] = buf.getvalue()
            if engine and out:
                # raw layers for materials.engine_material (variant_glb._engine_material)
                out["materials"] = "engine"
                for key, pat in (("specsize", "*_specSize_*.png"), ("glow", "*_glow_*.png")):
                    f = grab(pat, {"specsize": "specSize"}.get(key, key))
                    if f:
                        out[key] = _read_bytes(f)
            if out:
                if sheet:
                    out["sheet"] = sheet
                    if sname and sheet is not sheets[0]:
                        out["sheet_name"] = sheet.get("name")
                _blend_layer(out)
                return out
    return None


# TextureSheet "blend type" (the property's editor string in the executable:
# "items=standard:0,add:1,subtract:2,manual:3|caption=blend type").
BLEND_SUBTRACT = 2


def _blend_layer(layers):
    """A sheet that is not a plain alpha blend (watchmen_extract.sheet_blend):
    `subtract` (Rorschach's two inkblot layers) takes its texture AWAY from what is
    behind it -- white = full ink, black = nothing; `add` puts it on top as light.
    glTF has neither, and drawn as an ordinary texture such a layer would paint its
    black background over the surface.  The diffuse is rewritten by
    watchmen_extract.blend_layer_image (black ink / the lit colour, coverage in
    alpha) to be drawn alphaMode BLEND; layers['blend'] = the blend type and
    layers['blend_info'] = the sheet_blend dict tell variant_glb."""
    import watchmen_extract as _we

    info = _we.sheet_blend(layers.get("sheet"))
    if not info or info.get("gltf") not in ("ink", "glow") or "diffuse" not in layers:
        return
    try:
        import io
        from PIL import Image

        buf = io.BytesIO()
        _we.blend_layer_image(Image.open(io.BytesIO(layers["diffuse"])), info).save(buf, "PNG")
    except Exception:
        return
    layers["diffuse"] = buf.getvalue()
    layers["blend"] = info["type"]
    layers["blend_info"] = info
    layers.pop("alphaMask", None)


def header_order(header):
    """Byte order of an extracted asset header, read from the header itself
    (watchmen_extract.header_order: the [u32 length][class name] it opens with is
    valid in one order only).  None when the header does not say."""
    import watchmen_extract as we

    return we.header_order(header)


def model_order(mh, ms=None, name=None, log=print):
    """Byte order of a .model header: header_order(); only when the header does not
    say (never on the six shipped sets: 5,490 of 5,490 models say) the mesh
    descriptors decide -- a set that overruns the stream `ms` does not count, the
    larger set wins, a tie stays little-endian -- and that is logged."""
    import watchmen_extract as we

    o = header_order(mh)
    if o is not None:
        return o
    n = {}
    for bo in ("<", ">"):
        d = we.find_descriptors(mh, bo)
        if ms is not None and sum(nv * st + ib for nv, st, ib in d) > len(ms):
            d = []
        n[bo] = len(d)
    o = ">" if n[">"] > n["<"] else "<"
    if log is not None:
        log(
            "  WARNING: %s: byte order not stated by the header; %s-endian %s from the mesh "
            "descriptors (little %d, big %d)"
            % (
                name or "model",
                "big" if o == ">" else "little",
                "assumed (tie)" if n["<"] == n[">"] else "taken",
                n["<"],
                n[">"],
            )
        )
    return o


#: mesh pieces a loader could not decode since the last dropped_pieces(reset=True):
#: [{model, submesh, vertices, stride, index_bytes, byte_order, reason}]
_DROPPED = []


def note_dropped(model, submesh, nv, stride, ib, order, reason, log=print):
    """Record (and log, one line) a submesh that is NOT in the output."""
    rec = {
        "model": os.path.basename(model),
        "submesh": int(submesh),
        "vertices": int(nv),
        "stride": int(stride),
        "index_bytes": int(ib),
        "byte_order": "big" if order == ">" else "little",
        "reason": reason,
    }
    _DROPPED.append(rec)
    if log is not None:
        log(
            "  WARNING: %s: submesh %d (%d vertices, stride %d, %d index bytes, %s-endian) NOT "
            "exported: %s" % (rec["model"], submesh, nv, stride, ib, rec["byte_order"], reason)
        )
    return rec


def dropped_pieces(reset=False):
    """The pieces noted since the last reset, each (model, submesh) once."""
    seen, out = set(), []
    for r in _DROPPED:
        k = (r["model"], r["submesh"])
        if k not in seen:
            seen.add(k)
            out.append(dict(r))
    if reset:
        del _DROPPED[:]
    return out


def flat_buffer(ms, off, nv, stride, ib, order):
    """Stream offset of a PLANAR submesh's vertex buffer (one flat axis: the eye
    card of Large_Head_2), searched only after the strict scan found nothing --
    the fallback watchmen_extract.decode_model uses (_vb_ok_flat).  None when
    there is none.  (Large_Head_2 submesh 3: 69803, the offset the header-driven
    layout of the PC file gives.)"""
    import watchmen_extract as we

    c = off
    while c <= min(off + 65536, len(ms) - nv * stride - ib):
        if (
            we._sane(struct.unpack_from(order + "f", ms, c)[0])
            and we._vb_ok_flat(ms, c, nv, stride, ib, order)
            and we._ib_ok(ms, c, nv, stride, ib, order)
        ):
            return c
        c += 1
    return None


NO_BUFFER = "no vertex buffer with a valid index buffer found in the stream"
NO_TRIANGLES = "the buffer found holds no valid triangle"


def load_parts(models, bn, sheets=None):
    """Decode skinned mesh parts for the given bind bone-name order.
    models: .model base paths (no extension).  Returns variant_glb parts list
    with engine-exact submesh->material mapping.
    sheets: {model base name (lower case): {texture key: sheet name}} -- the
    texture sheets a variant selects (characters_export.variant_sheets); a part
    with such a texture gets a material of its own (sheet_ref)."""
    import watchmen_extract as we, extract_skeletons as es, rig_glb
    import variant_glb as _vg

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
        mh = _read_bytes(base + ".model")
        ms = _read_bytes(base + ".model.stream")
        plat = we.console_platform_for(base + ".model")  # decides the console colour order
        # byte order: console (X360/PS3) model headers/streams are big-endian.
        # The header says which (model_order); counting descriptors per order tied
        # on single-submesh models and picked a false little-endian one.
        order = model_order(mh, ms, os.path.basename(base))
        be = order == ">"
        plist = [x for _, x in es._ordered_names(mh, order)]
        pf = [x for x in plist if _slot(x) is not None]
        ppal = [pf[(k - 1) % len(pf)] for k in range(len(pf))]  # engine rotate-by-one
        remap = np.array([_slot(n) for n in ppal], dtype=np.int64)
        descs = we.find_descriptors(mh, order)
        mats = we.extract_materials(mh)
        sel = (sheets or {}).get(os.path.basename(base).lower())
        if sel:
            mats = [sheet_ref(m, sel.get(we.texture_key(m.path or ""))) for m in mats]
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
                vbo = flat_buffer(ms, off, nv, stride, ib, order)
            if vbo is None:
                note_dropped(base, si_, nv, stride, ib, order, NO_BUFFER)
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
                note_dropped(base, si_, nv, stride, ib, order, NO_TRIANGLES)
                continue
            SI = remap[np.clip(np.asarray(skidx, int), 0, len(remap) - 1)]
            parts.append(
                _vg.with_attrs(
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
                    ),
                    # header-driven attributes for the buffer the scan found
                    _vg.buffer_vertex_attrs(mh, ms, order, vbo, nv, stride, plat),
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


def build_lib(bind, models, clips, out, animroot, texroots=(), upsample=2, track_names="exact"):
    """bind: npz path; models: iterable of .model base paths (no extension);
    clips: iterable of clip names; out: .glb path; animroot: extracted
    Animation dir; texroots: texture trees (<root>/**/<mat>.bmp/*_diffuse_*.png);
    track_names: bake_v4.bake's track lookup ("exact" or "prefix")."""
    import bake_v4
    import variant_glb as vg

    bake_v4._load_bind(bind)
    bank = _clip_bank(animroot)
    bv = np.load(bind, allow_pickle=True)
    bn = [str(x) for x in bv["names"]]
    parts = load_parts(models, bn)
    print("parts:", len(parts))
    anims = []
    for clip in clips:
        p_, dur = bake_v4.bake(clip, upsample, bank=bank, track_names=track_names)
        fps = bake_v4.fps_for(len(p_), dur)  # header-exact (docs/ENGINE_CONSTANTS.md)
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
    import characters_export

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
            track_names=characters_export.track_names_for(extract_out),
        )
        print("  wrote", out)
        done.append(out)
    return done
