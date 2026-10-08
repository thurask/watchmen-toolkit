"""glTF materials from the engine's TextureSheet (one implementation for the
character writer, `extract --glb` and the MTL roughness bake).

The game's colour pass (DeferredMain2PS, read from the shader bytecode; CPU side
REDeferredMain2::SetMaterial 0x571d5d) lights display-encoded values with

    n     = specularSize                      (sheet +0x90), or with a specSize layer
            (specSize.g^2 * 256 + 1) * specularSize         per texel
    spec  = specularPower * NH / (n - n*NH + NH)             per light, times N.L
    lit   = albedo * (ambient + sum C*NL + G) + specTex * (G + sum C*NL*spec)
    G     = selfIlluminanceColor * selfIlluminance * glow
    rim   = falloffGradient(N.V) * fallOffPower * (light sums + fallOffColor)   (renderType 10)

Missing layers default to (0x5382aa): normal grey 128 (Gfx+0x598); specular, glow,
fallOff, ambOcc white (+0x59c); height and specSize black (+0x5a0).  `engine` mode
translates that into glTF's metallic-roughness model; `legacy` leaves the writers as they were
(flat 0.85 roughness / roughnessGen.png, raw specMap as specularColorTexture).

A material the game draws NO highlight on (specularPower <= 0 without a cube
reflection, or a reflectance of nothing) is written fully rough -- roughnessFactor
1.0, no metallicRoughnessTexture, specularFactor 0 -- so that it is matte also in
a viewer that ignores KHR_materials_specular."""

import io
import math
import os

MODES = ("engine", "legacy")
#: materials written when neither the caller nor $WATCHMEN_MATERIALS says otherwise
DEFAULT_MODE = "engine"
#: experimental switches, also "k=v,k=v" in $WATCHMEN_MATERIAL_OPTS
OPTIONS = {
    # KHR_materials_sheen for falloff sheets (not closer to the engine in the render
    # test in both viewers: off; the exact parameters are always in extras)
    "sheen": 0,
    "sheen_scale": 1.0,
    "sheen_roughness": 0.5,
    # 1: the lobe is matched in display space (the engine adds the highlight to
    # display values, a glTF viewer adds it in linear light); 0: plain formulas
    "display": 1,
    "emissive": 1,
    "spec_scale": 1.0,
    "refl_floor": 1.0,
    "rough_scale": 1.0,
}
#: sheet properties copied to material.extras.watchmen.sheet
EXTRA_KEYS = (
    "renderType",
    "specularSize",
    "specularPower",
    "selfIlluminance",
    "selfIlluminanceColor",
    "bloomPower",
    "opacity",
    "alphaThreshold",
    "twoSided",
    "reflectionType",
    "reflectionLightFactor",
    "fallOffPower",
    "fallOffColor",
    "depthFadeGradient",
    "blendType",
    "srcBlend",
    "dstBlend",
    "blendOp",
    "writeDepthBuffer",
    "normalMapPower",
    "enableNormalMapping",
    "fresnelPower",
    "maxReflection",
)
RENDER_FALLOFF = 10
#: render types drawn blended by a pass of their own (SkyBox, Sprite; 0x589dd9, 0x582eb6)
OWN_PASS_BLENDED = (7, 9)
#: render types whose sheet opacity (< 0.99) fades the part: 0 and 10 are moved to
#: the blended list for it (0x5739d0), 7 is blended by the sky pass with the
#: opacity as the pixel shader's alpha factor (0x589dd9); None = type not known
FADED_BY_OPACITY = (None, 0, 7, 10)


def mode(value=None):
    """The material mode in force: `value`, else $WATCHMEN_MATERIALS, else DEFAULT_MODE."""
    v = value or os.environ.get("WATCHMEN_MATERIALS") or DEFAULT_MODE
    if v not in MODES:
        raise ValueError("materials mode %r (one of %s)" % (v, ", ".join(MODES)))
    return v


def options(over=None):
    o = dict(OPTIONS)
    for kv in (os.environ.get("WATCHMEN_MATERIAL_OPTS") or "").split(","):
        k, _, v = kv.partition("=")
        if k.strip() in o and v:
            o[k.strip()] = float(v)
    o.update(over or {})
    return o


def srgb_to_linear(c):
    """sRGB EOTF, extended above 1 (numpy array or float)."""
    import numpy as np

    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((np.maximum(c, 0.0) + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    import numpy as np

    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.maximum(c, 0.0) ** (1 / 2.4) - 0.055)


def exponent(spec_size, g=None):
    """The engine's specular exponent: specularSize, times (g^2*256 + 1) with a
    specSize layer value g in 0..1."""
    n = float(spec_size) if spec_size and spec_size > 0 else 15.0
    if g is None:
        return n
    return (g * g * 256.0 + 1.0) * n


def roughness(n):
    """glTF (perceptual) roughness of a lobe of exponent n: GGX alpha^2 = 2/(n+2),
    roughness = sqrt(alpha).  (sqrt(2/(n+2)), the old bake, is alpha itself.)"""
    import numpy as np

    return np.clip((2.0 / (np.asarray(n, dtype=np.float64) + 2.0)) ** 0.25, 0.045, 1.0)


def f0(n, intensity, spec=1.0):
    """Reflectance at normal incidence whose GGX peak equals the engine's
    unnormalised peak specularPower * specTex: 4 * alpha^2 * I * spec."""
    import numpy as np

    return np.clip(8.0 * float(intensity) * spec / (np.asarray(n, dtype=np.float64) + 2.0), 0, 1)


#: engine_material()'s `specular` for a material the game draws no highlight on
NO_HIGHLIGHT = {"specularFactor": 0.0}


def no_highlight(sheet, intensity=None, spec_black=False):
    """True when the game draws no specular highlight with this sheet, from the
    sheet values alone: specularPower (or `intensity` when given) <= 0 and no
    cube reflection (reflectionType 2 with a reflectionLightFactor), or a
    specular layer that is black everywhere (`spec_black`).  engine_material()
    reaches the same answer from the reflectance (max F <= 1e-6); this is the
    rule for writers that do not build the material (the MTL of `extract`)."""
    s = sheet or {}
    if spec_black:
        return True
    i = float(s.get("specularPower") or 0.0) if intensity is None else float(intensity)
    k = float(s.get("reflectionLightFactor") or 0.0) if s.get("reflectionType") == 2 else 0.0
    return i <= 0.0 and k <= 0.0


def gradient(text):
    """TextureSheet gradient string "pos,r,g,b,a|..." -> f(t in 0..1) -> rgb list.
    Keys sit at int(pos * 1000) (FUN_00413360); before the first key the first
    colour, after the last the last, linear in between; no key: white (FUN_00411783)."""
    keys = []
    for k in (text or "").split("|"):
        f = k.split(",")
        if len(f) >= 4:
            try:
                keys.append((int(float(f[0]) * 1000.0), [float(x) for x in f[1:4]]))
            except ValueError:
                pass
    keys.sort(key=lambda k: k[0])

    def ev(t):
        if not keys:
            return [1.0, 1.0, 1.0]
        ti = int(float(t) * 1000.0)
        if ti < keys[0][0] or len(keys) == 1:
            return list(keys[0][1])
        for (p0, c0), (p1, c1) in zip(keys, keys[1:]):
            if ti < p1:
                f = (ti - p0) / float(p1 - p0) if p1 > p0 else 0.0
                return [a + f * (b - a) for a, b in zip(c0, c1)]
        return list(keys[-1][1])

    return ev


def alpha(sheet, tex_has_alpha, vertex_alpha=False, pixel_alpha=None):
    """-> (alphaMode or None, alphaCutoff or None, baseColor alpha factor or None).

    The render list is the sheet's renderType (0x5739d0): 0 / 10 / 11 are drawn
    opaque with depth write and blending off (0x57552b), alpha-TESTED (>=
    alphaThreshold/255) when the diffuse texture has alpha -- hair included; type
    1, or opacity < 0.99 on a type 0 / 10 sheet, goes to the sorted blended list.
    A SkyBox (7) sheet is filed in list 7, which the "Sky boxes" pass draws
    (0x56f9fb -> RESkyBox 0x58bc85 -> 0x589dd9): that pass sends the sheet's
    opacity to the pixel shader as c0.w, the shader writes alpha = texture alpha *
    vertex alpha * c0.w (SkyBoxPS), and the standard blend type is SRCALPHA /
    INVSRCALPHA -- so the opacity of a type-7 sheet fades it, with or without
    vertex alpha (opacity 0: nothing is drawn).  With blend type add or subtract
    the sky pass uses ONE / ONE and the alpha does not enter; the factor is
    written all the same.
    So BLEND iff renderType == 1, or opacity < 0.99 on a type 0 / 7 / 10 sheet (or
    one whose type is not known); else MASK when the diffuse has alpha; else
    opaque.  An opacity below 0.99 on any other type (glass, water, hair, wet ...)
    does not move the part to the blended list (0x5739d0) and is not written as a
    fade; whether those passes use it is not established, and no sheet of the six
    game sets has one.  Vertex alpha multiplies the texture alpha but never
    chooses the list: on its own it does not make a material BLEND (how it enters
    the shader output is from the shader bytecode, not re-read with the lists),
    except on a SkyBox sheet, whose pass blends.  A Sprite (9)
    sheet on a model part is filed in render list 9, which the deferred frame never
    draws (0x5739d0, 0x56f9fb); type-9 sheets are drawn by Sprite nodes (0x4c85e8)
    with the sheet's blend triple (watchmen_extract.sheet_blend); for them, and
    where the sheet is not known
    (no renderType: a texture without sheet.json), the rule is unchanged: BLEND
    when the vertex alpha varies.

    tex_has_alpha: the engine's test is the texture header's alpha flag
    (0x429e77 -> 0x571d5d); callers pass that flag where the extract recorded it
    (sheet.json "textureHasAlpha"), else whether the pixels carry alpha.
    pixel_alpha (None = same as tex_has_alpha): whether any texel is below 255.
    A flagged texture whose alpha is 255 everywhere and whose mesh has no vertex
    alpha passes the test everywhere and is written opaque; a blended sheet with
    nothing below full alpha is written opaque as well."""
    sheet = sheet or {}
    op = sheet.get("opacity")
    rt = sheet.get("renderType")
    low = op is not None and float(op) < 0.99
    # 0x5739d0 moves only types 0 and 10 to the blended list for their opacity; the
    # sky pass (type 7) blends with the sheet opacity itself (0x589dd9, c0.w).  A
    # material that is blended anyway (type 1, or vertex alpha in a pass of its
    # own) keeps the factor
    fade = low and rt in FADED_BY_OPACITY
    varies = bool(tex_has_alpha if pixel_alpha is None else pixel_alpha) or bool(vertex_alpha)
    if vertex_alpha and (rt is None or rt in OWN_PASS_BLENDED):
        return "BLEND", None, (round(float(op), 6) if low else None)
    if rt == 1 or fade:
        if not (varies or low):
            return None, None, None
        return "BLEND", None, (round(float(op), 6) if low else None)
    if tex_has_alpha and varies:
        thr = sheet.get("alphaThreshold")
        if thr is None:
            return "MASK", 0.5, None
        if thr > 0:
            return "MASK", round(min(int(thr), 255) / 255.0, 6), None
    return None, None, None


def texture_has_alpha(sheet_json, pixel_alpha):
    """The engine's "texture has alpha" for a diffuse layer -> (flag, from_header).
    sheet_json: the sheet.json of the texture the diffuse layer comes from (the
    override texture when the sheet takes its diffuse elsewhere); its
    "textureHasAlpha" is the Texture header's alpha byte of layer 0, written by
    the texture pass.  Absent (an older extract, or a texture without a sheet):
    the pixel extrema `pixel_alpha`."""
    v = (sheet_json or {}).get("textureHasAlpha")
    if isinstance(v, bool):
        return v, True
    return bool(pixel_alpha), False


def _png(arr, mode_):
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(arr, mode_).save(buf, "PNG")
    return buf.getvalue()


def _arr(img, mode_, size):
    """PIL image / png bytes -> float array 0..1 resized to `size` (w, h), or None."""
    import numpy as np
    from PIL import Image

    if img is None:
        return None
    if isinstance(img, (bytes, bytearray)):
        img = Image.open(io.BytesIO(img))
    img = img.convert(mode_)
    if size and img.size != size:
        img = img.resize(size, Image.BILINEAR)
    return np.asarray(img, dtype=np.float64) / 255.0


def engine_material(sheet, diffuse=None, spec=None, specsize=None, glow=None, opts=None):
    """Sheet + layer images (PIL images or PNG bytes; any may be None) -> dict:

    roughnessFactor, mr (ORM png | None; a material without a highlight, `specular`
    == NO_HIGHLIGHT, always has roughness 1.0 and no mr), specular {specularFactor,
    specularColorFactor} | None, spec (specularColorTexture png, sRGB | None),
    ior | None, emissiveFactor | None, emissive (png | None), emissiveStrength |
    None, sheen {..} | None, extras {..}.  Nothing here touches alpha or culling."""
    import numpy as np

    o = options(opts)
    s = sheet or {}
    P = {"mr": None, "spec": None, "specular": None, "ior": None, "sheen": None}
    P["emissiveFactor"] = P["emissive"] = P["emissiveStrength"] = None
    intensity = float(s.get("specularPower") or 0.0)
    size = None
    for im in (specsize, spec, diffuse):
        if im is not None and not isinstance(im, (bytes, bytearray)):
            size = im.size
            break
    g = _arr(specsize, "L", None)
    n = exponent(s.get("specularSize"), g)
    sp = _arr(spec, "RGB", g.shape[1::-1] if g is not None else None)
    alb = _arr(diffuse, "RGB", None)
    base = float(alb.mean()) if alb is not None else 0.5
    # --- lobe width.  The engine's lobe lives in display space; seen through the
    # sRGB curve a linear lobe of exponent n' looks like one of exponent n'/gamma,
    # gamma = the local slope of the curve around the lit base (1 on white, ~2.2
    # on black).
    gam = 1.0
    if o["display"]:
        lo = min(max(0.6 * base, 0.02), 0.95)
        hi = min(lo + max(min(intensity, 1.0), 0.05), 1.0)
        if hi > lo:
            gam = float(
                math.log(float(srgb_to_linear(hi)) / float(srgb_to_linear(lo))) / math.log(hi / lo)
            )
            gam = min(max(gam, 1.0), 2.4)
    r = np.clip(roughness(np.asarray(n) * gam) * o["rough_scale"], 0.045, 1.0)
    if g is not None and float(np.ptp(r)) > 1.0 / 255:
        orm = np.zeros(g.shape + (3,), np.uint8)
        orm[..., 0] = 255
        orm[..., 1] = np.round(r * 255.0)
        P["mr"] = _png(orm, "RGB")
        P["roughnessFactor"] = 1.0
    else:
        P["roughnessFactor"] = round(float(np.mean(r)), 4)
    # --- strength.  F0 = 4 alpha^2 * (linear radiance of the engine's peak).
    k = float(s.get("reflectionLightFactor") or 0.0) if s.get("reflectionType") == 2 else 0.0
    if intensity <= 0.0 and k <= 0.0:
        P["specular"] = {"specularFactor": 0.0}
    else:
        spv = sp if sp is not None else 1.0
        peak = intensity * spv
        if o["display"]:
            lo = min(max(0.6 * base, 0.0), 1.0)
            # the screen saturates at 1: so does the highlight the engine shows
            peak = srgb_to_linear(np.minimum(lo + peak, 1.0)) - srgb_to_linear(lo)
        alpha2 = 2.0 / (np.asarray(n) * gam + 2.0)
        if sp is not None and g is not None:
            alpha2 = alpha2[..., None]
        F = np.clip(4.0 * alpha2 * peak * o["spec_scale"], 0.0, 1.0)
        F = np.maximum(F, np.clip(k * spv * o["refl_floor"], 0.0, 1.0))  # cube reflection floor
        fmax = float(np.max(F))
        if fmax <= 1e-6:
            P["specular"] = {"specularFactor": 0.0}
        else:
            if fmax <= 0.04:
                P["specular"] = {"specularFactor": round(fmax / 0.04, 4)}
            else:
                rt = math.sqrt(min(fmax, 0.9))
                P["ior"] = round((1.0 + rt) / (1.0 - rt), 4)
                P["specular"] = {"specularFactor": 1.0}
            rel = np.asarray(F / fmax, dtype=np.float64)
            if rel.ndim >= 2 and float(np.ptp(rel)) > 1.0 / 255:
                if rel.ndim == 2:
                    rel = np.repeat(rel[..., None], 3, 2)
                P["spec"] = _png(np.round(linear_to_srgb(rel) * 255.0).astype(np.uint8), "RGB")
    # --- no highlight at all.  The game draws none here, so the material must not
    # show one in any viewer: a viewer without KHR_materials_specular would draw
    # the default dielectric highlight at the sheet's (often low, per-texel)
    # roughness -- wet-looking hair, brows and eyes.  With the extension the lobe
    # is off and the roughness is not seen, so nothing changes there.
    if P["specular"] == NO_HIGHLIGHT:
        P["roughnessFactor"] = 1.0
        P["mr"] = None
    # --- emission: G * (albedo + specTex), display values
    si = float(s.get("selfIlluminance") or 0.0)
    if si > 0.0 and o["emissive"]:
        col = np.asarray(s.get("selfIlluminanceColor") or [1.0, 1.0, 1.0], dtype=np.float64) * si
        ref = alb if alb is not None else np.full((1, 1, 3), 0.5)
        hw = ref.shape[1::-1]
        gl = _arr(glow, "RGB", hw)
        spe = _arr(spec, "RGB", hw)
        e = col * (gl if gl is not None else 1.0) * (ref + (spe if spe is not None else 1.0))
        # linear radiance that, added to the lit base, shows as base + e on screen
        lit = 0.6 * ref if o["display"] else 0.0
        el = srgb_to_linear(lit + e) - srgb_to_linear(lit)
        emax = float(el.max())
        if emax > 1e-4:
            if emax > 1.0:
                P["emissiveStrength"] = round(emax, 4)
                el = el / emax
            e = linear_to_srgb(el)
            P["emissiveFactor"] = [1.0, 1.0, 1.0]
            P["emissive"] = _png(np.round(np.clip(e, 0, 1) * 255.0).astype(np.uint8), "RGB")
    # --- falloff rim (no glTF equivalent; sheen is the nearest and optional)
    if s.get("renderType") == RENDER_FALLOFF and o["sheen"]:
        ev = gradient(s.get("depthFadeGradient"))
        rim = np.asarray(ev(0.1)) * float(s.get("fallOffPower") or 0.0)
        rim = rim * (np.asarray(s.get("fallOffColor") or [1, 1, 1], dtype=np.float64) + 0.5)
        col = np.clip(srgb_to_linear(np.clip(rim * o["sheen_scale"], 0, 1)), 0, 1)
        if float(col.max()) > 1e-4:
            P["sheen"] = {
                "sheenColorFactor": [round(float(x), 4) for x in col],
                "sheenRoughnessFactor": round(float(o["sheen_roughness"]), 4),
            }
    ex = {k_: s[k_] for k_ in EXTRA_KEYS if k_ in s}
    P["extras"] = ex
    if s.get("overrides"):  # layers the sheet takes from another texture (0x4991f0)
        ex["overrides"] = dict(s["overrides"])
    P["size"] = size
    return P


def apply(j, mat, P, add_texture):
    """Write engine_material()'s result into glTF material `mat` of document `j`.
    add_texture(png_bytes, label) -> texture index."""
    used = j.setdefault("extensionsUsed", [])

    def ext(name):
        if name not in used:
            used.append(name)
        return mat.setdefault("extensions", {}).setdefault(name, {})

    pbr = mat.setdefault("pbrMetallicRoughness", {})
    pbr["metallicFactor"] = 0
    pbr["roughnessFactor"] = P["roughnessFactor"]
    pbr.pop("metallicRoughnessTexture", None)
    if P["mr"] is not None:
        pbr["metallicRoughnessTexture"] = {"index": add_texture(P["mr"], "mr")}
    if P["specular"] is not None:
        e = ext("KHR_materials_specular")
        e.clear()
        e.update(P["specular"])
        if P["spec"] is not None:
            e["specularColorTexture"] = {"index": add_texture(P["spec"], "spec")}
    if P["ior"] is not None:
        ext("KHR_materials_ior")["ior"] = P["ior"]
    if P["emissiveFactor"] is not None:
        mat["emissiveFactor"] = P["emissiveFactor"]
        if P["emissive"] is not None:
            mat["emissiveTexture"] = {"index": add_texture(P["emissive"], "emissive")}
        if P["emissiveStrength"] is not None:
            ext("KHR_materials_emissive_strength")["emissiveStrength"] = P["emissiveStrength"]
    if P["sheen"] is not None:
        ext("KHR_materials_sheen").update(P["sheen"])
    if not used:
        j.pop("extensionsUsed", None)
    w = mat.setdefault("extras", {}).setdefault("watchmen", {})
    w["materials"] = "engine"
    if P["extras"]:
        w["sheet_values"] = P["extras"]


# --------------------------------------------------------------------------
# Level grade: the GFXEffect nodes of the level fragments (REPostProcess 0x57e044
# reads them; members from GFXEffect::RegisterMembers 0x4c0af2).
# --------------------------------------------------------------------------
#: property (lower case) -> kind
GRADE_PROPS = {
    "fog": "truth",
    "fogbegin": "number",
    "fogend": "number",
    "fogcolor": "vector",
    "enablefilters": "truth",
    "bloomweight": "number",
    "bloomcontrast": "number",
    "bloombrightness": "number",
    "brightness": "number",
    "saturation": "number",
    "contrast": "number",
    "tintpower": "number",
    "tintcolor": "vector",
    "gamma": "number",
    "noiseintensity": "number",
    "noisetexture": "text",
    "skyboxblur": "number",
    "edgedetectgradient": "number",
    "edgedetectcutoff": "integer",
    "shadowblurpower": "number",
    "enableaa": "truth",
    "enabledof": "truth",
    "focaldist": "number",
    "focalnearfalloff": "number",
    "focalfarfalloff": "number",
    "maxfocalblur": "number",
    "globalgeometrylodfactor": "number",
    "geometrylodmode": "integer",
    "globallightfadestart": "number",
    "globallightfadeend": "number",
    "globalshadowpower": "number",
    "shadowmaxrange": "number",
    # script properties of FXGfxEffectCtrl: whose node it is.  initialize_external
    # 0x73ccb6 hands the node to the PlayerCtrl of playable character _iplayerctrl
    # (data: 0 on the "RS GFX" nodes, 1 on "NO GFX"; 2 = both) as its camera's grade
    "m_tinitialgfxnode": "truth",
    "_iplayerctrl": "integer",
}
GRADE_FORMULA = (
    "c = scene + materialBloom + blurred(bloomFilter(scene)) * bloomWeight; c += brightness; "
    "c += (c - mean(c)) * saturation; c += (c - 0.5) * contrast; "
    "c = saturate(lerp(c, c * tintColor, tintPower)); c = c ** (1 / gamma); "
    "bloomFilter(x) = y + (y - 0.5) * bloomContrast with y = x + bloomBrightness.  All on "
    "display-encoded values.  The bloom filter, the grade and gamma apply only when the node "
    "is enabled, in the scene, the fill mode is solid and enableFilters is set; otherwise "
    "they are the identity.  Noise additionally needs a noiseTexture and noiseIntensity > 0.  "
    "Depth of field (enableDOF) and edge anti-aliasing (enableAA, with the render option) "
    "are NOT under enableFilters.  The post pass takes these values from the camera's own "
    "node, else from the global node = the first enabled GFXEffect node in the scene.  "
    "fog (per vertex, before the grade): lerp(colour, fogColor, 1 - saturate((fogEnd - dist) "
    "/ (fogEnd - fogBegin))), always from the global node (as LOD, light fade and shadow "
    "values), never from the camera's node.  On screen, brightness / contrast / gamma / "
    "saturation are the node's value plus platform_adjustment"
)
#: what the options script adds to the node's brightness / contrast / gamma /
#: saturation (FXGfxEffectCtrl 0x73c139 contrast, 0x73c1e5 brightness, 0x73c28f
#: gamma, 0x73c33a saturation; MapValueCenter 0x73504c; centres per platform from
#: InitializePlatform 0x735084, platform ids 1 PC / 2 X360 / 3 PS3 from 0x47ff8c).
#: Multipliers and centres read from the exe bytes.  The options start at 0.5
#: (0x82be66); nothing here is applied to the nodes.
PLATFORM_ADJUSTMENT = {
    "map": "m(v, c) = c + 2 * (1 - c) * (v - 0.5) if v > 0.5 else 2 * c * v; "
    "v = the option value 0..1, c = the platform's centre for that option",
    "formulas": {
        "contrast": "node.contrast + (m(v, c) - 0.5) * 1.1",
        "brightness": "node.brightness + (m(v, c) - 0.5) * 0.5",
        "gamma": "node.gamma + (m(v, c) - 0.5) * 1.2",
        "saturation": "max(node.saturation + (m(v, c) - 0.5) * 1.5, -1)",
    },
    "multipliers": {"contrast": 1.1, "brightness": 0.5, "gamma": 1.2, "saturation": 1.5},
    "pc": {"gamma": 0.6, "brightness": 0.6, "contrast": 0.6, "saturation": 0.5},
    "x360": {"gamma": 0.5, "brightness": 0.7, "contrast": 0.6, "saturation": 0.5},
    "ps3": {"gamma": 0.4, "brightness": 0.4, "contrast": 0.2, "saturation": 0.5},
    "other": {"gamma": 0.5, "brightness": 0.5, "contrast": 0.5, "saturation": 0.5},
    "option_default": 0.5,
    "default_offsets": {
        "pc": {"gamma": 0.12, "brightness": 0.05, "contrast": 0.11, "saturation": 0.0},
        "x360": {"gamma": 0.0, "brightness": 0.1, "contrast": 0.11, "saturation": 0.0},
        "ps3": {"gamma": -0.12, "brightness": -0.05, "contrast": -0.33, "saturation": 0.0},
    },
    "note": "centres 'other' = the editor flag set or any other platform id; the four "
    "options start at 0.5 (SettingsState.command_set_default_settings 0x82be66, read on "
    "PC; the console executables were not read); a saved profile replaces them; the node "
    "values in this file are as stored, without the adjustment",
}


def grade_adjustment(platform, value):
    """What the options script adds to a node's values at option value `value`
    (0..1, the same for the four options here) on `platform` ("pc" / "x360" /
    "ps3" / "other") -> {"gamma", "brightness", "contrast", "saturation"}."""
    centres = PLATFORM_ADJUSTMENT[platform]
    v = float(value)
    out = {}
    for k in ("gamma", "brightness", "contrast", "saturation"):
        c = centres[k]
        m = c + 2.0 * (1.0 - c) * (v - 0.5) if v > 0.5 else 2.0 * c * v
        out[k] = round((m - 0.5) * PLATFORM_ADJUSTMENT["multipliers"][k], 6)
    return out


def _grade_value(kind, v):
    import struct

    if kind == "vector":
        return [round(float(x), 6) for x in v] if isinstance(v, (list, tuple)) else None
    if kind == "truth":
        return bool(v)
    if kind == "integer":
        return int(v)
    if kind == "text":
        return v if isinstance(v, str) else None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, int):  # an undecoded 4-byte value: the bits of a float
        return round(struct.unpack("<f", struct.pack("<I", v & 0xFFFFFFFF))[0], 6)
    return round(float(v), 6)


def fragment_grades(fragment_json):
    """kapow fragment JSON (watchmenlib.fragment_json_file) -> [{"node", "type",
    "enabled", <GRADE_PROPS values>}] for every GFXEffect node in it.  A level can
    hold several (the shipped levels have one per playable character, "RS GFX" /
    "NO GFX").  `_iplayerctrl` says whose camera a node grades (0 / 1 = that
    playable character, 2 = both; FXGfxEffectCtrl.initialize_external 0x73ccb6)
    and `m_tinitialgfxnode` is the script's "initial node" flag, both as stored;
    later changes of the active node (fades) are the game script's and are not
    decided here."""
    out = []
    for nd in (fragment_json or {}).get("nodes_full") or []:
        typ = nd.get("type") or ""
        if "GFXEffect" not in typ:
            continue
        rec = {"node": None, "type": typ}
        for p in nd.get("props") or []:
            if len(p) < 3:
                continue
            key = str(p[0]).lower()
            if key == "name":
                rec["node"] = p[2]
            elif key == "enabled":
                rec["enabled"] = bool(p[2])
            elif key in GRADE_PROPS:
                try:
                    val = _grade_value(GRADE_PROPS[key], p[2])
                except (TypeError, ValueError):
                    val = None
                if val is not None:
                    rec[key] = val
        if "gamma" in rec or "tintcolor" in rec:
            out.append(rec)
    return out


def level_grades(extract_out, to_json):
    """Every GFXEffect node of the fragments under <extract_out>/extracted/Levels.
    to_json: path -> fragment JSON (watchmenlib.fragment_json_file)."""
    root = os.path.join(str(extract_out), "extracted")
    if not os.path.isdir(root):
        root = str(extract_out)
    levels = {}
    for dp, _dn, fn in sorted(os.walk(root)):
        for f in sorted(fn):
            if not f.lower().endswith(".fragment"):
                continue
            path = os.path.join(dp, f)
            try:
                with open(path, "rb") as fh:
                    if b"GFXEffect" not in fh.read():
                        continue
                g = fragment_grades(to_json(path))
            except Exception:
                continue
            if g:
                levels[os.path.relpath(path, root).replace("\\", "/")] = g
    return {
        "format": "watchmen-grade-meta/1",
        "formula": GRADE_FORMULA,
        "platform_adjustment": PLATFORM_ADJUSTMENT,
        "fragments": levels,
    }
