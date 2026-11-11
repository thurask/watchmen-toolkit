"""The material switches of a Texture header (its TextureSheet records): the
properties and their engine names (`TEXTURE_SHEET_PROPS`, `SHEET_PROPERTIES`,
`SHEET_RENDER_TYPES`), the sheets of a header (`texture_sheet`,
`texture_sheets`, `select_sheet`, `first_sheet`), the blend settings
(`sheet_blend`, `blend_layer_image`, `blend_material`), the specular record
(`extract_specular`), and the `sheet.json` written beside each texture
(`write_sheet_json`, `read_sheet_json`, `mark_texture_decode`,
`mark_stored_name`).
"""

import functools
import os
import struct
import sys
from pathlib import Path

# the flat wlib modules import each other by name (`import kapow_props`); one path
# setup for this module, also when it is run as a script or loaded by file path.
# Append, never insert(0): flat module names must not shadow the stdlib.
_WLIB = os.path.dirname(os.path.abspath(__file__))
if _WLIB not in sys.path:
    sys.path.append(_WLIB)
import extract_log  # noqa: E402
import kapow_block  # noqa: E402
import texture_header  # noqa: E402


# WM07 stores per-texture material params in the texture header as 64-bit
# name-hashed records (verified against the game's pixel shader: $specularData.xy).
_SPEC_HI = 0xBDA17DE4
_SPEC_EXP = 0xF4142D28  # specular exponent (Blinn-Phong power)  -> c2.x
_SPEC_INT = 0xB3AB3306  # specular intensity (0 = matte)         -> c2.y


#: TextureSheet properties (texturesheet.cpp registration strings, exe 0xA2F7A7..);
#: name -> property type.  The record is [salt u32][name hash u32][type hash u32]
#: [tag u32][value], both hashes being kapow_hash of the strings.
TEXTURE_SHEET_PROPS = {
    "renderType": "integer",
    "isLit": "truth",
    "alphaThreshold": "integer",
    "writeDepthBuffer": "truth",
    "twoSided": "truth",
    "blendType": "integer",
    "opacity": "number",
    "normalMapPower": "number",
    "enableNormalMapping": "truth",
}
#: renderType values (exe dropdown string "Standard:0,Standard with blending:1,...")
SHEET_RENDER_TYPES = {
    0: "standard",
    1: "blend",
    2: "glass",
    3: "water",
    6: "hair",
    7: "skybox",
    9: "sprite",
    10: "falloff",
    11: "wet",
}


@functools.cache
def sheet_hashes():
    """{name: name hash} of TEXTURE_SHEET_PROPS and their three types (read-only)."""
    return {
        nm: kapow_block._name_hash(nm)
        for nm in list(TEXTURE_SHEET_PROPS) + ["integer", "truth", "number"]
    }


def texture_sheet(header, order="<"):
    """Material properties of a Texture header's FIRST TextureSheet (the one in
    use unless a collection node selects another; a header can hold further named
    sheets, see face_rule.texture_sheets) -> {name: value} for
    TEXTURE_SHEET_PROPS, or {} when the header has none.

    twoSided is the byte the renderer turns into D3DCULL_NONE (FUN_00571d5d,
    sheet+0xA4); renderType 1 is "Standard with blending"; alphaThreshold is the
    alpha-test reference (0..255) of the standard type; normalMapPower scales the
    normal map's x and y ($effectFactors.x)."""
    H = sheet_hashes()
    n = len(header)
    salt = None
    rt = H["renderType"]
    ti = H["integer"]
    # the first offset o (0 <= o < n - 20) with [renderType hash][integer hash] at
    # o + 4: a bytes search
    p = header.find(struct.pack(order + "II", rt, ti), 4)
    if 0 <= p - 4 < n - 20:
        start = p - 4
        salt = struct.unpack_from(order + "I", header, start)[0]
    if salt is None:
        # older record layout (standalone Part 1, PC / X360): no type hash to find
        for sh in _untyped_sheets(header, order):
            if "renderType" in sh:
                return {
                    k: (sh[k] & 0xFFFFFFFF) if TEXTURE_SHEET_PROPS[k] == "integer" else sh[k]
                    for k in TEXTURE_SHEET_PROPS
                    if k in sh
                }
        return {}
    out = {}
    want = {H[k]: k for k in TEXTURE_SHEET_PROPS}
    pat = struct.pack(order + "I", salt)
    o = header.find(pat, start)
    while 0 <= o < n - 20:  # every offset holding the salt, in order (overlaps too)
        s0, lo, hi = struct.unpack_from(order + "III", header, o)
        o_next = header.find(pat, o + 1)
        if lo not in want:
            o = o_next
            continue
        nm = want[lo]
        typ = TEXTURE_SHEET_PROPS[nm]
        if hi != H[typ] or nm in out:
            o = o_next
            continue
        match typ:
            case "number":
                out[nm] = struct.unpack_from(order + "f", header, o + 16)[0]
            case "truth":
                out[nm] = bool(struct.unpack_from(order + "I", header, o + 16)[0])
            case _:
                out[nm] = struct.unpack_from(order + "I", header, o + 16)[0]
        o = o_next
    return out


#: every property of a TextureSheet (TextureSheet::RegisterMembers 0x526589), in
#: the order a Texture header stores them
SHEET_PROPERTIES = (
    "name uniqueID renderType isLit selfIlluminance selfIlluminanceColor normalMapPower "
    "specularPower specularSize bloomPower opacity shadowPower alphaThreshold "
    "writeDepthBuffer castShadow receiveShadow twoSided enableNormalMapping enablePOM "
    "enableAnimation animationDelayInMs reflectionType depthFogPower depthFadeScale "
    "depthFadeGradient depthFadeGradientAlpha useWaterDepthFade glassThickness "
    "materialColor materialColorAlpha fresnelPower waterEffectFadeRange "
    "reflectionBumpPower refractionBumpPower reflectionLightFactor waterNormalType "
    "maxReflection uScrollSpeed vScrollSpeed u2ScrollSpeed v2ScrollSpeed resetUVOffset "
    "heightScale heightBias numHeightSamples numLightSamples secondaryHighlightShift "
    "highlightBumpScale blendType srcBlend dstBlend blendOp fallOffPower fallOffColor "
    "renderOrder lodPOMDistance lodPOMFadeOut lodNormalMapDistance lodNormalMapFadeOut "
    "diffuseMapOverride normalMapOverride glowMapOverride heightMapOverride "
    "specularMapOverride fallOffMapOverride ambOccMapOverride specSizeMapOverride "
    "diffuseMapChannel normalMapChannel glowMapChannel heightMapChannel "
    "specularMapChannel fallOffMapChannel ambOccMapChannel specSizeMapChannel "
    "inheritDeferredLight"
).split()
#: <layer>MapOverride property -> the layer label the texture carve uses.
#: Engine (read): the draw path asks the mesh's sheet for each layer through
#: 0x49c838(sheet, layer) -> 0x4991f0: the override texture of that layer when the
#: sheet has one (handles at sheet+0x190 diffuse, +0x19c normal, +0x1a8 specular,
#: +0x1b4 glow, +0x1c0 height, +0x1cc fallOff, +0x1d8 ambOcc, +0x1e4 specSize), else
#: the sheet's own texture (+0x64); then the SAME layer of that texture (0x49be2d).
#: Any sheet, the first included.  Called from the material binds at 0x58a849,
#: 0x58acd0, 0x571da8, 0x589d35 ...
SHEET_LAYER_OVERRIDES = {
    "diffuseMapOverride": "diffuse",
    "normalMapOverride": "normal",
    "specularMapOverride": "specMap",
    "specSizeMapOverride": "specSize",
    "glowMapOverride": "glow",
    "heightMapOverride": "height",
    "fallOffMapOverride": "fallOff",
    "ambOccMapOverride": "ambOcc",
}
#: blendType (exe dropdown "standard:0,add:1,subtract:2,manual:3")
SHEET_BLEND_TYPES = {0: "standard", 1: "add", 2: "subtract", 3: "manual"}
#: srcBlend / dstBlend and blendOp of blend type `manual` (the D3DBLEND / D3DBLENDOP values)
SHEET_BLEND_FACTORS = {
    1: "zero",
    2: "one",
    3: "srcColor",
    4: "invSrcColor",
    5: "srcAlpha",
    6: "invSrcAlpha",
    7: "dstAlpha",
    8: "invDstAlpha",
    9: "dstColor",
    10: "invDstColor",
    11: "srcAlphaSat",
}
SHEET_BLEND_OPS = {1: "add", 2: "subtract", 3: "revSubtract", 4: "max", 5: "min"}
_T_UNIQUE_ID = 0xEDEF427C  # type hash of the uniqueID record


@functools.cache
def sheet_keys():
    """{name hash: SHEET_PROPERTIES name, ("type", type hash): type} (read-only)."""
    keys = {kapow_block._name_hash(nm): nm for nm in SHEET_PROPERTIES}
    for t in ("number", "integer", "truth", "string", "vector", "color"):
        keys[("type", kapow_block._name_hash(t))] = t
    keys[("type", _T_UNIQUE_ID)] = "id"
    return keys


def _untyped_sheets(header, order="<", raw=False):
    """TextureSheet objects of a Texture header in the OLDER record layout
    ([salt][name hash][payload dwords][payload], no type hash: standalone Part 1
    on PC / X360) -> [{property: value}] in file order, [] when the header has
    none.  Exact: each `[u32 13]["TextureSheet\0"][u32 dwords]` object must read
    to its end (kapow_props.read_records); value types are the ones the typed
    builds store for the same properties (kapow_props.untyped_types).  With
    `raw`, a property is kept under its name whatever it is; otherwise only
    SHEET_PROPERTIES, as texture_sheets() returns them."""
    kp = kapow_block.props_module()
    K = sheet_keys()
    ut = kp.untyped_types()
    names = kp.namedict() if raw else {}
    out = []
    for ob in kp.find_objects(header, order, ("TextureSheet",)):
        if ob["layout"] != "untyped":
            continue
        sh = {}
        for _o, key, _th, q, k in ob["records"]:
            nm = K.get(key) or names.get(key)
            if nm is None:
                continue
            val = kp.record_value(ut.get(key), header, q, k, order)
            if val is None and ut.get(key) != "string":
                continue  # no known type for this property: not guessed
            if isinstance(val, list):
                val = [round(x, 6) for x in val]
            sh.setdefault(nm, val)
        out.append(sh)
    return out


def texture_sheets(header, order="<"):
    """Every TextureSheet of a Texture header, in file order -> [dict].

    A texture holds one or more named sheets (material settings); the first is the
    one in use unless a model instance names another by its uniqueID
    (`textureSheetsDescription`, BaseModel 0x4a56c2 -> sheet lookup 0x524caf, which
    falls back to the first sheet).  Each dict has the sheet's stored properties
    (SHEET_PROPERTIES: `name`, `uniqueID`, renderType, blendType, twoSided,
    alphaThreshold, specularSize / specularPower, the UV scroll speeds ...) and
    `overrides` {layer label: texture asset path} for the non-empty
    <layer>MapOverride strings: the sheet takes that layer from another texture.

    Records are [salt u32][name hash u32][type hash u32][payload dwords u32]
    [payload]; all records of one sheet share the salt."""
    K = sheet_keys()
    n = len(header)
    sheets, by_salt = [], {}
    o = 0
    while o + 16 <= n:
        salt, key, typ, cnt = struct.unpack_from(order + "IIII", header, o)
        nm, ty = K.get(key), K.get(("type", typ))
        if nm is None or ty is None or not 1 <= cnt <= 4096 or o + 16 + 4 * cnt > n:
            o += 1
            continue
        p = o + 16
        match ty:
            case "number":
                val = struct.unpack_from(order + "f", header, p)[0]
            case "truth":
                val = bool(struct.unpack_from(order + "I", header, p)[0])
            case "integer":
                val = struct.unpack_from(order + "i", header, p)[0]
            case "id":
                hi, lo = struct.unpack_from(order + "II", header, p) if cnt >= 2 else (0, 0)
                val = (hi << 32) | lo
            case "string":
                val = header[p + 4 : p + 4 * cnt].split(b"\0", 1)[0].decode("latin-1")
            case _:  # vector / color
                val = [round(x, 6) for x in struct.unpack_from(order + "%df" % cnt, header, p)]
        sh = by_salt.get(salt)
        if sh is None:
            sh = by_salt[salt] = {"overrides": {}}
            sheets.append(sh)
        if nm in SHEET_LAYER_OVERRIDES:
            if val:
                sh["overrides"].setdefault(SHEET_LAYER_OVERRIDES[nm], val)
        else:
            sh.setdefault(nm, val)
        o = p + 4 * cnt
    # a sheet has a render type; anything else that matched is not one
    sheets = [sh for sh in sheets if "renderType" in sh]
    if not sheets:  # older record layout (standalone Part 1, PC / X360)
        for src in _untyped_sheets(header, order):
            if "renderType" not in src:
                continue
            sh = {"overrides": {}}
            for nm, val in src.items():
                if nm in SHEET_LAYER_OVERRIDES:
                    if val:
                        sh["overrides"].setdefault(SHEET_LAYER_OVERRIDES[nm], val)
                else:
                    sh[nm] = val
            sheets.append(sh)
    return sheets


def select_sheet(sheets, ref=None):
    """The sheet `ref` names among `sheets` (texture_sheets / sheet.json "sheets"):
    None -> the first; an int -> the one with that uniqueID; a str -> by name.  An
    unknown id or name gives the first sheet, as the engine does (0x4a56c2)."""
    if not sheets:
        return {}
    if ref is not None:
        for sh in sheets:
            if (isinstance(ref, int) and sh.get("uniqueID") == ref) or (
                isinstance(ref, str) and sh.get("name") == ref
            ):
                return sh
    return sheets[0]


def sheet_blend(sheet):
    """How the sheet's surface is combined with what is behind it -> dict or None.

    Read from the render-state setup (0x582eb6; RESkyBox 0x589dd9 for render type
    7) and the list routing (0x5739d0).  The render types "Standard with
    blending" (1), SkyBox (7) and Sprite (9) blend; so does a Standard (0) or
    FallOff (10) sheet whose opacity is below 0.99, which the engine moves to the
    blended list and draws with the sheet's own blendType (the opacity of the
    model instance and the LOD weight multiply in at run time and are not known
    here).  {"type": standard | add | subtract | manual, "src", "dst", "op": the
    D3D blend factors / operator the engine sets, "gltf": how a glTF material can
    show it -- "exact" (alpha blending), "ink" (subtract: black with the texture's
    brightness as coverage), "glow" (add: emissive with the brightness as
    coverage) or None (no glTF expression), "cause": "renderType" | "opacity" (why
    the sheet is in a blended list), "pass": "sky" (render type 7, drawn by
    RESkyBox) or "standard" (every other type), which blend_material's opacity
    rule asks}."""
    if not sheet:
        return None
    rt = sheet.get("renderType", 1)
    cause = "renderType"
    if rt not in (1, 7, 9):
        op = sheet.get("opacity")
        if rt not in (0, 10) or op is None or not float(op) < 0.99:
            return None
        cause = "opacity"
    bt = sheet.get("blendType") or 0
    sky = rt == 7
    match bt:
        case 0:  # standard
            src, dst, op = 5, 6, 1
        case 1:  # add
            src, dst, op = (2, 2, 1) if sky else (5, 2, 1)
        case 2:  # subtract
            src, dst, op = (2, 2, 2) if sky else (5, 2, 3)
        case 3:  # manual
            src, dst, op = (
                sheet.get("srcBlend", 5),
                sheet.get("dstBlend", 6),
                sheet.get("blendOp", 1),
            )
        case _:
            return None
    if (src, dst, op) == (5, 6, 1):
        how = "exact"
    elif op == 1 and dst == 2 and src in (2, 5):
        how = "glow"
    elif op == 3 and dst == 2 and src in (2, 5):
        how = "ink"
    else:
        how = None
    return {
        "type": SHEET_BLEND_TYPES.get(bt, str(bt)),
        "src": SHEET_BLEND_FACTORS.get(src, src),
        "dst": SHEET_BLEND_FACTORS.get(dst, dst),
        "op": SHEET_BLEND_OPS.get(op, op),
        "gltf": how,
        "cause": cause,
        "pass": "sky" if sky else "standard",
    }


def blend_layer_image(img, blend):
    """The diffuse layer as a glTF base colour for a blend that is not plain alpha
    blending (sheet_blend "gltf" ink / glow); `img` and the result are PIL images.

    ink  (engine: dst - src.rgb * src.a): black, alpha = brightness * alpha.  Drawn
         alphaMode BLEND it removes the same share of a white surface; over a darker
         one it removes proportionally less than the game does.
    glow (engine: dst + src.rgb * src.a): the colour at full brightness, alpha =
         brightness * alpha; with the same image as emissive texture a BLEND material
         adds src.rgb * src.a, and dims what is behind it by that alpha, which the
         game does not."""
    from PIL import Image, ImageChops

    how = (blend or {}).get("gltf")
    if how not in ("ink", "glow"):
        return img
    rgba = img.convert("RGBA")
    r, g, b, a = rgba.split()
    if how == "ink":
        cov = ImageChops.multiply(rgba.convert("L"), a)
        zero = Image.new("L", rgba.size, 0)
        return Image.merge("RGBA", (zero, zero, zero, cov))
    import numpy as _np

    peak = ImageChops.lighter(ImageChops.lighter(r, g), b)
    cov = ImageChops.multiply(peak, a)
    c = _np.asarray(rgba, _np.float32)[..., :3]
    m = _np.maximum(_np.asarray(peak, _np.float32), 1.0)[..., None]
    full = _np.clip(c * 255.0 / m + 0.5, 0, 255).astype(_np.uint8)
    out = _np.dstack([full, _np.asarray(cov, _np.uint8)])
    return Image.fromarray(out, "RGBA")


def blend_material(mat, blend, emissive_index=None, opacity=None):
    """Write `blend` (sheet_blend) into the glTF material dict `mat`: alphaMode,
    the emissive part of a glow, and extras.watchmen with the engine's blend.
    opacity: the sheet's opacity.  A glow drawn by the sky pass whose source factor
    is the source alpha (a manual SRCALPHA / ONE blend on a SkyBox sheet) adds
    src.rgb * src.a, and the alpha SkyBoxPS writes carries the opacity (texture
    alpha * vertex alpha * opacity, read from code), so an opacity below 1 scales
    the emissiveFactor.  ONE / ONE (blend type add in the sky pass) does not read
    the alpha and keeps factor 1.  A SRCALPHA / ONE glow of the standard pass
    (blend type add on a "with blending" sheet, or such a manual blend) keeps
    factor 1 as well: that this pass multiplies the sheet opacity into the alpha
    is not read from code (the item alpha of 0x5739d0 holds it)."""
    if not blend or blend["type"] == "standard":
        return mat
    how = blend.get("gltf")
    info = {"blend": blend["type"], "src": blend["src"], "dst": blend["dst"], "op": blend["op"]}
    if how == "ink":
        mat["alphaMode"] = "BLEND"
        mat.pop("alphaCutoff", None)
        info["note"] = (
            "engine blend type %s (dst - src): baseColorTexture is the layer "
            "rewritten as black with alpha = the game texture's brightness" % blend["type"]
        )
    elif how == "glow":
        mat["alphaMode"] = "BLEND"
        mat.pop("alphaCutoff", None)
        mat.setdefault("pbrMetallicRoughness", {})["baseColorFactor"] = [0.0, 0.0, 0.0, 1.0]
        fade = 1.0
        if (
            opacity is not None
            and blend["src"] == SHEET_BLEND_FACTORS.get(5)
            and blend.get("pass") == "sky"
        ):
            fade = min(max(float(opacity), 0.0), 1.0)
        if emissive_index is not None:
            mat["emissiveTexture"] = {"index": emissive_index}
            mat["emissiveFactor"] = [round(fade, 6)] * 3
        if fade < 1.0:
            info["opacity"] = round(fade, 6)
        info["note"] = (
            "engine blend type %s (dst + src): the layer at full brightness is the "
            "emissive texture, alpha = the game texture's brightness" % blend["type"]
        )
    elif how == "exact":
        mat["alphaMode"] = "BLEND"
        mat.pop("alphaCutoff", None)
    else:
        info["note"] = "this blend has no glTF expression; the material is written unblended"
    mat.setdefault("extras", {}).setdefault("watchmen", {}).update(info)
    return mat


def write_sheet_json(header, out_dir, order="<"):
    """sheet.json next to the layer PNGs.  Top level: the FIRST sheet's material
    switches for the GLB writers (two-sided, blend, alpha threshold, normal-map
    power) and its layer `overrides`; "sheets": every sheet of the texture with
    all its properties (texture_sheets)."""
    try:
        sh = texture_sheet(header, order)
        if sh:
            import json as _json

            full = texture_sheets(header, order)
            flag = texture_header.texture_alpha_flag(
                header, order, getattr(out_dir, "name", out_dir)
            )
            if flag is not None:  # not a sheet property: the header's alpha byte of layer 0
                sh = dict(sh, textureHasAlpha=flag)
            ex = texture_header.parse_texture_frames(header, order)
            if ex:  # facts of the header itself, beside the sheet values
                slots0 = ex["frames"][0]["slots"]
                if slots0[0] and slots0[0]["type"] == 2:
                    sh = dict(sh, cubeFaceOrder=list(texture_header.CUBE_FACE_ORDER))
                if ex.get("anim_tail"):
                    ms = texture_header.texture_frame_ms(ex["anim_tail"], len(ex["frames"]))
                    sh = dict(sh, animation=ex["anim_tail"])
                    if any(m is not None for m in ms):
                        sh["frame_ms"] = ms
            if full:
                sh = dict(sh)
                if full[0]["overrides"]:
                    sh["overrides"] = full[0]["overrides"]
                if len(full) > 1 or "name" in full[0]:
                    sh["sheets"] = full
            with open(out_dir / "sheet.json", "w", encoding="utf-8", newline="\n") as _f:
                _f.write(_json.dumps(sh, sort_keys=True))
    except Exception as e:  # the texture is still written; its materials lose the sheet
        sheet_warning(out_dir, "sheet.json not written", e)


def sheet_warning(out_dir, what, e):
    """One WARNING line for a sheet.json that could not be written or updated."""
    extract_log.warn(
        "      WARNING: texture %s: %s (%s: %s)"
        % (getattr(out_dir, "name", out_dir), what, type(e).__name__, e)
    )


def read_sheet_json(tex_dir):
    """sheet.json of an extracted texture directory -> dict ({} if absent; {} and
    a WARNING line when it is there but cannot be read)."""
    import json as _json

    try:
        with open(os.path.join(str(tex_dir), "sheet.json"), encoding="utf-8") as _f:
            d = _json.load(_f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:  # ValueError: not JSON, not UTF-8
        sheet_warning(Path(str(tex_dir)), "sheet.json not readable, read as empty", e)
        return {}
    return d if isinstance(d, dict) else {}


def extract_specular(header, order="<"):
    """Return (exponent, intensity) from the FIRST material block in a Texture
    header -- the engine's $specularData.xy. exponent drives the specular power,
    intensity scales the specular highlight (0 -> matte). Ground-truthed against an
    apitrace capture (nightowlbelt 20/0.58, RorschachButton 27.6/0.52).
    order '<' PC / '>' console (the 64-bit name hash + float are byte-order-flipped
    on the big-endian consoles)."""
    exp = inten = None
    n = len(header)
    for o in range(0, n - 20):
        hlo, hhi = struct.unpack_from(order + "II", header, o + 4)
        if hhi == _SPEC_HI:
            if hlo == _SPEC_EXP and exp is None:
                exp = struct.unpack_from(order + "f", header, o + 16)[0]
            elif hlo == _SPEC_INT and inten is None:
                inten = struct.unpack_from(order + "f", header, o + 16)[0]
            if exp is not None and inten is not None:
                break
    if exp is None and inten is None:
        # older record layout (no type hash to match): the first sheet's records
        # of the same two properties (specularSize 0xF4142D28, specularPower 0xB3AB3306)
        for sh in _untyped_sheets(header, order):
            if "renderType" in sh:
                return sh.get("specularSize"), sh.get("specularPower")
    return exp, inten


#: sheet.json key that lists what a texture carve could not decode (absent when
#: every layer the header describes was written).
TEXTURE_DECODE_KEY = "decodeWarnings"


def mark_texture_decode(out_dir, notes):
    """Record `notes` (a list of strings) under TEXTURE_DECODE_KEY in the texture
    directory's sheet.json, creating the file when the texture has no sheet."""
    if not notes:
        return
    try:
        import json as _json

        js = read_sheet_json(out_dir)
        js[TEXTURE_DECODE_KEY] = list(notes)
        with open(out_dir / "sheet.json", "w", encoding="utf-8", newline="\n") as _f:
            _f.write(_json.dumps(js, sort_keys=True))
    except Exception as e:
        sheet_warning(out_dir, "decode notes not recorded in sheet.json", e)


def mark_stored_name(out_dir, stored):
    """Record the archive's spelling of a texture that was written under its
    canonical name (--names canonical) as "stored_name" in the texture
    directory's sheet.json.  A texture without a sheet.json gets none (the
    folders of two archives must hold the same files): its stored name is in
    _canonical_names.json only.  Nothing is written when `stored` is empty."""
    if not stored or not (out_dir / "sheet.json").is_file():
        return
    try:
        import json as _json

        js = read_sheet_json(out_dir)
        js["stored_name"] = stored
        with open(out_dir / "sheet.json", "w", encoding="utf-8", newline="\n") as _f:
            _f.write(_json.dumps(js, sort_keys=True))
    except Exception as e:
        sheet_warning(out_dir, "stored_name not recorded in sheet.json", e)


def first_sheet(texdir):
    """The texture's first sheet with all its properties, from sheet.json ({} when
    the texture has none): the top-level switches overlaid on "sheets"[0] (srcBlend /
    dstBlend / blendOp of a manual blend are only in "sheets").  The one reader of
    the MTL writer, mtl_no_highlight and rig_glb."""
    sheet = read_sheet_json(texdir)
    full = sheet.get("sheets")
    if isinstance(full, list) and full and isinstance(full[0], dict):
        sheet = full[0] | {k: v for k, v in sheet.items() if k != "sheets"}
    return sheet
