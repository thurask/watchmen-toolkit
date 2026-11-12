"""Models as OBJ + MTL: the carved textures of an extract found by the asset
path a model stores (`TextureIndex`, `build_texture_index`, `resolve_texture`,
`sheet_layer_dirs`, `find_layer`), one material name per texture
(`unique_material_names`), the MTL statements a texture sheet decides
(`mtl_no_highlight`, `mtl_const_roughness`, `mtl_ns_of_roughness`; roughness
maps), and the writer (`write_obj_mtl`; `materials_mode`).
"""

import os
import re
import sys
from pathlib import Path

# the flat wlib modules import each other by name (`import kapow_props`); one path
# setup for this module, also when it is run as a script or loaded by file path.
# Append, never insert(0): flat module names must not shadow the stdlib.
_WLIB = os.path.dirname(os.path.abspath(__file__))
if _WLIB not in sys.path:
    sys.path.append(_WLIB)
from wutil import rel_path  # noqa: E402
import extract_log  # noqa: E402
import material_refs  # noqa: E402
import texture_sheet  # noqa: E402


def sheet_layer_dirs(tex_index, sheet, warn=None):
    """{layer label: texture dir} for the layers `sheet` takes from another texture
    (its <layer>MapOverride paths), resolved in `tex_index`; missing ones are left out."""
    out = {}
    for layer, path in sorted((sheet or {}).get("overrides", {}).items()):
        d = resolve_texture(tex_index, material_refs.texture_ref(path), warn) if tex_index else None
        if d is not None:
            out[layer] = d
    return out


#: directory-name endings that mark a carved texture (`<asset name>/<layer>.png`)
TEXTURE_DIR_EXTS = (".bmp", ".tga", ".dds", ".png", ".jpg", ".texture")


class TextureIndex(dict):
    """Carved-texture lookup for one `textures/` tree.

    As a dict it is bare name (lower case) -> texture dir, and
    independent of the order the file system lists directories in.  `resolve()` is
    the lookup to use: by the asset path the model stores when there is one, by
    bare name otherwise.  When a bare name fits several directories the one whose
    asset path sorts first (lower case, '/'-separated) is taken and a warning lists
    the candidates.

    by_path:    {texture_key(asset path): dir}
    candidates: {bare name: [dir, ...]} in tie-break order"""

    def __init__(self, tex_root=None, require_diffuse=True):
        dict.__init__(self)
        self.root = None if tex_root is None else Path(tex_root)
        self.by_path = {}
        self.candidates = {}
        self._warned = set()
        if self.root is None:
            return
        found = []
        try:
            for dp, dns, fns in os.walk(str(self.root)):
                dns.sort(key=lambda d: (d.lower(), d))
                if dp == str(self.root):
                    continue
                has_dif = any("_diffuse_" in f and f.lower().endswith(".png") for f in fns)
                named = os.path.basename(dp).lower().endswith(TEXTURE_DIR_EXTS)
                if has_dif or (named and not require_diffuse):
                    rel = os.path.relpath(dp, str(self.root)).replace(os.sep, "/")
                    found.append((material_refs.texture_key(rel), rel, Path(dp)))
        except (OSError, ValueError) as e:  # ValueError: relpath across drives
            extract_log.warn(
                "      WARNING: texture index of %s incomplete (%s: %s)"
                % (self.root, type(e).__name__, e)
            )
        for key, _rel, d in sorted(found, key=lambda t: (t[0], t[1])):
            self.by_path.setdefault(key, d)
            name = d.name.rsplit(".", 1)[0].strip().lower()
            self.candidates.setdefault(name, []).append(d)
            self.setdefault(name, d)

    def ambiguous(self):
        """{bare name: [dir, ...]} for every name carried by more than one texture."""
        return {k: list(v) for k, v in self.candidates.items() if len(v) > 1}

    def resolve(self, ref, warn=None):
        """Texture dir for a TexRef / asset path / bare name, or None.

        1. the asset path (TexRef.path, or `ref` itself when it contains a '/'),
        2. else the bare name; if several textures carry it, the first candidate
           (asset paths sorted) -- reported once through `warn` (stderr if None)."""
        path = getattr(ref, "path", None)
        text = str(ref)
        if path is None and ("/" in text or "\\" in text):
            path, text = text, material_refs.material_stem(text)
        if path:
            d = self.by_path.get(material_refs.texture_key(path))
            if d is not None:
                return d
        name = text.strip().lower()
        cands = self.candidates.get(name)
        if not cands:
            return self.get(name)
        if len(cands) > 1 and name not in self._warned:
            self._warned.add(name)
            msg = "texture name %r is ambiguous (%s): using %s; candidates: %s" % (
                text,
                ("asset path %s is not in the texture tree" % path) if path else "no asset path",
                self._rel(cands[0]),
                ", ".join(self._rel(c) for c in cands),
            )
            if warn is None:
                print("  ! " + msg, file=sys.stderr)
            else:
                warn("      ! " + msg)
        return cands[0]

    def _rel(self, d):
        try:
            return rel_path(d, self.root).replace(os.sep, "/")
        except Exception:
            return str(d)


def build_texture_index(tex_root, require_diffuse=True):
    """TextureIndex of `tex_root`: bare name (lower) -> texture output dir (which holds
    <j>_<label>_<WxH>_<FMT>.png), plus path lookup -- see TextureIndex.resolve."""
    return TextureIndex(tex_root, require_diffuse)


def resolve_texture(tex_index, ref, warn=None):
    """Texture dir for material `ref` in `tex_index` (a TextureIndex, or a plain
    {bare name: dir} dict), or None."""
    if not tex_index:
        return None
    if hasattr(tex_index, "resolve"):
        return tex_index.resolve(ref, warn)
    return tex_index.get(str(ref).lower())


def unique_material_names(mats):
    """Names for a model's material list in which two textures that share a bare
    name but not a path stay apart: the second gets '<name>__2', the third '__3'.
    Everything else keeps its name."""
    first, out = {}, []
    for m in mats:
        k = getattr(m, "path", None)
        k = material_refs.texture_key(k) if k else None
        seen = first.setdefault(str(m), [])
        if k not in seen:
            seen.append(k)
        n = seen.index(k)
        out.append(str(m) if n == 0 else "%s__%d" % (m, n + 1))
    return out


def find_layer(texdir, label):
    try:
        g = sorted(texdir.glob("*_%s_*.png" % label))
    except OSError as e:
        texture_sheet.sheet_warning(texdir, "%s layer not looked up" % label, e)
        return None
    return g[0] if g else None


def _make_roughness(texdir, specsize_png, exponent):
    """Bake a Blender roughness map matching the game's specular model.
    With a specSize map (full variant): per-pixel exponent = (specSize^2*256+1)*expScale.
    Without (specMap-only): a flat exponent = expScale. roughness = sqrt(2/(exp+2)).
    expScale is the texture's $specularData.x. Cached as roughnessGen.png."""
    import math

    out = texdir / "roughnessGen.png"
    if out.exists():
        return out
    expscale = exponent if (exponent and exponent > 0) else 15.0
    try:
        import numpy as np
        from PIL import Image

        if specsize_png is not None:
            # specSize drives the per-pixel Blinn-Phong exponent = specSize^2*256+1.
            # (The material's expScale/c2.x is NOT applied here -- it crushes the whole
            # map to near-black/mirror; the specSize map alone gives the right, properly
            # oriented variation: high specSize -> glossy -> low roughness.)
            g = np.asarray(Image.open(specsize_png).convert("L"), dtype=np.float32) / 255.0
            expo = g * g * 256.0 + 1.0
            # The L8 specSize layer reads as a matte/roughness map in practice
            # (high value -> matte). Verified against in-engine renders: roughness
            # must INCREASE with specSize, so invert the exponent->roughness curve.
            rough = 1.0 - np.sqrt(2.0 / (expo + 2.0))
            Image.fromarray((np.clip(rough, 0.0, 1.0) * 255.0).astype("uint8")).save(out)
        else:
            # Flat (no specSize): roughness from the material exponent, INVERTED to
            # match in-engine renders (consistent with the per-pixel path). Low-exp
            # skin -> matte. roughness = 1 - sqrt(2/(exp+2)).
            rv = 1.0 - min(1.0, math.sqrt(2.0 / (expscale + 2.0)))
            r = int(round(min(1.0, max(0.0, rv)) * 255.0))
            Image.fromarray(np.full((4, 4), r, dtype="uint8")).save(out)
        return out
    except (OSError, ValueError) as e:  # Pillow cannot read the layer or write the map
        texture_sheet.sheet_warning(texdir, "%s not written, no map_Ns" % out.name, e)
        return None


def materials_mode():
    import materials as _mt

    return _mt.mode()


def mtl_no_highlight(texdir, inten, specmap_png):
    """materials.no_highlight for a texture of the MTL writer: `inten` is the
    spec.txt intensity (= the first sheet's specularPower, which is used when
    there is no spec.txt), the cube reflection comes from sheet.json, and a
    specMap that is black everywhere
    switches the highlight off as well.  Such a material gets `Ns 0` (roughness
    1 in Blender's importer) instead of its roughness (a roughnessEngine.png or
    a plain `Ns`), as its glTF material gets roughnessFactor 1.0 and no
    roughness texture."""
    try:
        import materials as _mt

        black = False
        if specmap_png is not None and not (inten is not None and inten <= 0.0):
            from PIL import Image

            ext = Image.open(specmap_png).convert("RGB").getextrema()
            black = max(hi for _lo, hi in ext) == 0
        sheet = texture_sheet.first_sheet(texdir)
        sb = texture_sheet.sheet_blend(sheet) if sheet else None
        if sb and sb.get("cause") == "opacity" and sb.get("gltf") not in ("ink", "glow"):
            sb = None  # blended for its opacity alone: rig_glb builds its engine material
        if not sheet or sb:
            return False  # the GLB writer builds no engine material for these either
        return _mt.no_highlight(sheet, inten, black)
    except (OSError, ValueError) as e:  # Pillow cannot read the specMap layer
        texture_sheet.sheet_warning(texdir, "specMap not read, highlight kept", e)
        return False


def _mtl_opacity(sheet):
    """`d` value of the MTL, or None: the sheet's opacity where the engine draws
    the part blended for it -- opacity < 0.99 and renderType 0 or 10 (0x5739d0) or
    7 (the sky pass, 0x589dd9)."""
    try:
        op = sheet.get("opacity")
        if op is not None and float(op) < 0.99 and sheet.get("renderType") in (0, 7, 10):
            return max(0.0, float(op))
    except (TypeError, ValueError):
        pass
    return None


def _mtl_emission(sheet):
    """What the MTL does with a glow layer -> (use it, Ke rgb | None).

    The engine adds G = selfIlluminanceColor * selfIlluminance * glow (materials.py
    header), so a glow layer shows only where the sheet's selfIlluminance is above
    0: then (True, colour * selfIlluminance clamped to 1).  selfIlluminance 0 (or
    below) -> (False, None): the layer is named in a comment and not linked (a
    level node can select another sheet of the texture, e.g. a lamp's "Lit" sheet
    after its "light off" one; a model file is written with the first sheet).  A
    texture without sheet values gives (True, None)."""
    si = (sheet or {}).get("selfIlluminance")
    if si is None or isinstance(si, bool):
        return True, None
    try:
        si = float(si)
        col = sheet.get("selfIlluminanceColor") or [1.0, 1.0, 1.0]
        ke = [min(1.0, max(0.0, float(c) * si)) for c in list(col)[:3]]
    except (TypeError, ValueError):
        return True, None
    if si <= 0.0 or len(ke) != 3:
        return False, None
    return True, ke


def mtl_const_roughness(exponent):
    """glTF roughness of a material without a specSize layer: the sheet's exponent
    alone (materials.roughness)."""
    import materials as _mt

    return float(_mt.roughness(_mt.exponent(exponent)))


def mtl_ns_of_roughness(r):
    """The MTL `Ns` that Blender's OBJ importer turns back into roughness r: it
    reads roughness = 1 - sqrt(Ns / 1000), so Ns = 1000 (1 - r)^2 (Ns 0 =
    roughness 1)."""
    r = min(1.0, max(0.0, float(r)))
    return 1000.0 * (1.0 - r) ** 2


def _make_roughness_engine(texdir, specsize_png, exponent):
    """roughnessEngine.png: glTF / Principled roughness of the engine's lobe,
    (2 / (n + 2)) ** 0.25 with n = specularSize, times (g^2 * 256 + 1) per texel with
    a specSize layer (DeferredMain2PS; materials.roughness).  The MTL writer calls
    it only for a texture with a specSize layer; without one (specsize_png None)
    it writes a flat 4x4 image of the one value, which the MTL writer puts as a
    plain `Ns` (mtl_ns_of_roughness) instead.  The legacy roughnessGen.png (1 - sqrt(2/(n+2)),
    sheet exponent ignored) is left alone."""
    out = texdir / "roughnessEngine.png"
    if out.exists():
        return out
    try:
        import numpy as np
        from PIL import Image
        import materials as _mt

        if specsize_png is not None:
            g = np.asarray(Image.open(specsize_png).convert("L"), dtype=np.float32) / 255.0
            r = _mt.roughness(_mt.exponent(exponent, g))
            Image.fromarray(np.round(r * 255.0).astype("uint8")).save(out)
        else:
            r = int(round(float(_mt.roughness(_mt.exponent(exponent))) * 255.0))
            Image.fromarray(np.full((4, 4), r, dtype="uint8")).save(out)
        return out
    except (OSError, ValueError) as e:  # Pillow cannot read the layer or write the map
        texture_sheet.sheet_warning(texdir, "%s not written, no map_Ns" % out.name, e)
        return None


def write_obj_mtl(path, name, v, n, uv, tris, subs, mats, tex_index, log):
    path.parent.mkdir(parents=True, exist_ok=True)

    def _san(x):
        return re.sub(r"[^0-9A-Za-z_.\-]", "_", x)

    def fv(a):
        if uv and n:
            return "%d/%d/%d" % (a, a, a)
        if n:
            return "%d//%d" % (a, a)
        if uv:
            return "%d/%d" % (a, a)
        return "%d" % a

    multi = len(subs) > 1
    names = [_san(x) for x in unique_material_names(mats)]
    mtl_path = path.with_suffix(".mtl")
    objdir = path.parent
    import frame as _frame

    # true frame (default): x negated; the faces stay in file order, which is the
    # counter-clockwise (front) order there.  mirrored: the engine numbers
    # verbatim (faces wind against the normals in a right-handed reader).
    true_frame = _frame.is_true()
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# %s  (%d verts, %d tris, %d submeshes)\n" % (name, len(v), len(tris), len(subs)))
        if true_frame:
            f.write("# %s %s (x = -engine x)\n" % (_frame.MARKER_KEY, _frame.TRUE))
        f.write("mtllib %s\n" % mtl_path.name)
        for p in v:
            if true_frame:
                p = (-p[0] + 0.0, p[1], p[2])
            f.write("v %.6f %.6f %.6f\n" % tuple(p))
        if uv:
            for u, w in uv:
                f.write("vt %.6f %.6f\n" % (u, 1.0 - w))
        if n:
            for nn in n:
                if true_frame:
                    nn = (-nn[0] + 0.0, nn[1], nn[2])
                f.write("vn %.6f %.6f %.6f\n" % tuple(nn))
        for si, (base, vc, tstart, tcount, st) in enumerate(subs):
            mat = names[si] if si < len(mats) else ("submesh_%d" % si)
            f.write(("o %s_%s\n" % (_san(name), mat)) if multi else ("o %s\n" % _san(name)))
            f.write("usemtl %s\n" % mat)
            for a, b, c in tris[tstart : tstart + tcount]:
                f.write("f %s %s %s\n" % (fv(a + 1), fv(b + 1), fv(c + 1)))
    # MTL: diffuse->map_Kd, normal->norm, specular->map_Ks, glossiness->map_Ns
    # (verified in Blender's importer: 'norm' is IGNORED; map_Bump routes through a
    # Normal Map node). map_Ns lands in Roughness, which is
    # gloss-inverted, but it links the map.
    seen = set()
    with open(mtl_path, "w", encoding="utf-8", newline="\n") as mf:
        mf.write("# materials for %s (textures linked from the textures/ dump)\n" % name)
        for raw, mm in zip(mats, names, strict=True):
            if mm in seen:
                continue
            seen.add(mm)
            mf.write("newmtl %s\n" % mm)
            mf.write("Kd 0.8 0.8 0.8\n")
            texdir = (
                None
                if (str(raw).startswith("submesh_") or not tex_index)
                else resolve_texture(tex_index, raw, log if callable(log) else None)
            )
            if texdir:

                def _rel(fp):
                    return rel_path(fp, objdir).replace("\\", "/")

                # per-texture specular params ($specularData.xy) written at carve time
                exp = inten = None
                sp = texdir / "spec.txt"
                if sp.exists():
                    try:
                        parts = sp.read_text().split()
                        exp = float(parts[0]) if len(parts) > 0 and parts[0] else None
                        inten = float(parts[1]) if len(parts) > 1 and parts[1] else None
                    except Exception:
                        pass
                # layers the texture's first sheet takes from another texture
                over = sheet_layer_dirs(
                    tex_index if hasattr(tex_index, "resolve") else None,
                    texture_sheet.read_sheet_json(texdir),
                    log if callable(log) else None,
                )
                dif = find_layer(over.get("diffuse", texdir), "diffuse")
                nrm = find_layer(over.get("normal", texdir), "normal")
                spm = find_layer(over.get("specMap", texdir), "specMap")
                sps = find_layer(over.get("specSize", texdir), "specSize")
                glw = find_layer(over.get("glow", texdir), "glow")
                sheet0 = texture_sheet.first_sheet(texdir) if materials_mode() == "engine" else {}
                if dif:
                    mf.write("map_Kd %s\n" % _rel(dif))
                    mf.write("map_d %s\n" % _rel(dif))  # transparency from diffuse alpha
                    fade = _mtl_opacity(sheet0)
                    if fade is not None:  # drawn blended for the sheet's opacity
                        mf.write("d %.4f\n" % fade)
                if nrm:
                    mf.write("map_Bump -bm 1.000000 %s\n" % _rel(nrm))
                # Specular gated by intensity (c2.y): intensity 0 => matte, no spec.
                matte = inten is not None and inten <= 0.0
                if matte:
                    mf.write("Ks 0 0 0\n")
                else:
                    spec_src = spm or sps
                    if spec_src:
                        mf.write("map_Ks %s\n" % _rel(spec_src))
                    if inten is not None:
                        k = min(1.0, inten)
                        mf.write("Ks %.4f %.4f %.4f\n" % (k, k, k))
                # Roughness from the real exponent (c2.x): baked with the specSize curve
                # where the texture has that layer, else one value as a plain Ns.
                if materials_mode() == "engine":
                    if mtl_no_highlight(texdir, inten, spm):
                        # the game draws no highlight: fully rough, and no bake
                        # (roughnessEngine.png would hold the sheet's narrow lobe)
                        rough = None
                        mf.write("Ns 0.000000\n")
                    elif sps:
                        rough = _make_roughness_engine(texdir, sps, exp)
                    else:
                        # a constant roughness is a plain Ns, not a one-value map
                        rough = None
                        r = mtl_const_roughness(exp)
                        mf.write("Ns %.6f\n" % mtl_ns_of_roughness(r))
                else:
                    rough = _make_roughness(texdir, sps, exp)
                if rough:
                    mf.write("map_Ns %s\n" % _rel(rough))
                if glw:
                    lit, ke = _mtl_emission(sheet0)
                    if ke is not None:
                        mf.write("Ke %.4f %.4f %.4f\n" % tuple(ke))
                    if lit:
                        mf.write("map_Ke %s\n" % _rel(glw))
                    else:  # the engine multiplies the layer with selfIlluminance = 0
                        others = [
                            s
                            for s in (texture_sheet.read_sheet_json(texdir).get("sheets") or [])[1:]
                            if isinstance(s, dict) and (s.get("selfIlluminance") or 0) > 0
                        ]
                        mf.write(
                            "# glow layer not linked (selfIlluminance 0 in the first sheet; "
                            "%d other sheet(s) of the texture light it): %s\n"
                            % (len(others), _rel(glw))
                        )
            mf.write("\n")
