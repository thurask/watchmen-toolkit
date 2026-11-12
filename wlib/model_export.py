"""One model asset to files: the mesh read where its header puts it, or by the
descriptor scan for a header neither layout reads, written as OBJ + MTL and,
with `--glb`, as a GLB (`decode_model`; its `status` dict says why a model
has no GLB), and the `<name>.model.json` sidecar (`model_meta`,
`model_meta_scanned`; `PARTS_NOTE`, `MORPH_CHANNEL_NOTE`).  `GlbOptions` holds
the `--glb` switches the caller passes to `decode_model` (`glb_options`).
"""

import dataclasses
import itertools
import os
import struct
import sys

# the flat wlib modules import each other by name (`import kapow_props`); one path
# setup for this module, also when it is run as a script or loaded by file path.
# Append, never insert(0): flat module names must not shadow the stdlib.
_WLIB = os.path.dirname(os.path.abspath(__file__))
if _WLIB not in sys.path:
    sys.path.append(_WLIB)
from wutil import order_name, platform_name  # noqa: E402
import extract_log  # noqa: E402
import kapow_block  # noqa: E402
import material_refs  # noqa: E402
import model_header  # noqa: E402
import model_mesh  # noqa: E402
import obj_mtl  # noqa: E402


# ---- rigged/textured .glb export (optional; --glb). FILE-DERIVED:
#      the flat skin rig takes its joint names + palette ORDER from the model's own
#      embedded skeleton header (extract_skeletons.skeleton_from_header); no
#      capture artifact (skeleton_female_biped.json / bundled_clip_*.npz) is
#      read. Emitted glbs are bind-pose; engine-exact ANIMATED per-character
#      glbs come from the file-only pipeline: `watchmen.py characters` (binds ->
#      bake -> variant glbs). ----
@dataclasses.dataclass(frozen=True)
class GlbOptions:
    """The `--glb` switches decode_model reads; decode_model writes no .glb
    without one.  `rig`: the loaded `rig_glb` module (glb_options loads it).
    `attrs`: also write the engine's per-vertex data (NORMAL, TANGENT,
    COLOR_0), sheet-driven materials and static .glb files for rigid models;
    --no-vertex-attrs clears it (the .glb output of releases before 1.4.0).
    `tex_size`: --glb-texture-size (None: embed the textures at full size).
    The rig layout is $WATCHMEN_RIG (--rig; variant_glb.rig_mode)."""

    rig: object
    attrs: bool = True
    tex_size: int | None = None


def glb_options(attrs=True, tex_size=None):
    """GlbOptions with `rig_glb` loaded.  Raises ImportError when it does not
    import."""
    import rig_glb

    return GlbOptions(rig_glb, attrs, tex_size)


def _model_palette(header, name=None):
    """Joint table for the --glb skin rig, decoded from the MODEL's own header
    (palette order = header node order: on the 92 body models of PC and Xbox 360
    Part 2 every weighted joint index names the bone the character export's
    rotate-by-one palette names, measured). Returns {'bone_count','bones':[{'name'}]}."""
    try:
        import extract_skeletons as _es

        sk = _es.skeleton_from_header(header, "palette")
    except (struct.error, ValueError, IndexError, KeyError) as e:
        extract_log.warn(
            "      WARNING: model %s: joint table not read from the header, joints named "
            "bone_<n> (%s: %s)" % (name or "?", type(e).__name__, e)
        )
        return None
    if sk and sk.get("bone_count"):
        return sk
    return None


def _model_is_body(header, name=None):
    """True if the model embeds a full biped body skeleton (has leg bones). Head /
    accessory models embed their own small palette (face bones, no legs) -- those must
    NOT be rigged with the shared body skeleton (their joint indices reference their own
    palette, which would otherwise collapse the head into the chest)."""
    try:
        import parse_model_nodes as _pmn

        names, _p, _q, _par = _pmn.parse(header)
        if len(names) <= 1:
            return True  # nothing decoded -> assume body, never silently unrig
        return any(("Calf" in n) or ("Thigh" in n) for n in names)
    except (struct.error, ValueError, IndexError, KeyError) as e:
        extract_log.warn(
            "      WARNING: model %s: node list not read from the header, rigged as a body "
            "(%s: %s)" % (name or "?", type(e).__name__, e)
        )
        return True  # default: treat as body (prior behaviour)


def _surface_summary(s):
    """One model_surfaces() element as it is written into <name>.model.json."""
    ids = {}
    for t in s["tris"]:
        ids[t["material_id"]] = ids.get(t["material_id"], 0) + 1
    return {
        "node": s["node"],
        "part": s["part"],
        "class": s["class"],
        "triangles": len(s["tris"]),
        "vertices": int(len(s["verts"])),
        "material_ids": {str(k): ids[k] for k in sorted(ids)},
        "weight_sum": round(s["weight_sum"], 6),
        "weight_is_area": s["weight_is_area"],
        # every weight exactly 1.0, whatever the triangle's area
        **({"weight_is_unit": True} if s.get("weight_is_unit") else {}),
    }


def _parts_summary(M):
    """The parts of a parse_model_header dict as <name>.model.json lists them."""
    xfs = model_header.model_part_transforms(M)
    out = []
    for pi, P in enumerate(M["parts"]):
        par = P["parent"]
        out.append(
            {
                "name": P["name"],
                "parent": par if 0 <= par < len(M["parts"]) else -1,
                "pos": [round(float(c), 6) for c in P["pos"]],
                "quat": [round(float(c), 6) for c in P["quat"]],
                "moved": xfs[pi] is not None,
                "pivotbook_index": P["f1"],
                "submeshes": [
                    {
                        "lod": li,
                        "name": sm["name"],
                        "shadow_id": sm["u28"],
                        "in_shadow_hull": bool(sm["u28"] > 0 and not sm["b24"]),
                        "primitive": model_header.PRIMITIVE_NAMES.get(
                            sm.get("primitive_type"), "type %s" % sm.get("primitive_type")
                        ),
                    }
                    for li, lod in enumerate(P["lods"])
                    for sm in lod
                ],
                "shadow_hulls": len(P["shadow"]),
                "occluder": bool(P.get("occluder")),
            }
        )
    return out


PARTS_NOTE = (
    "parts: the model's nodes in file order.  pos / quat are the part's local transform as "
    "stored (engine numbers; a vector rotates as conj(q)·v·q), parent -1 = none; `moved` = "
    "the chain up to the root is not the identity.  Vertices are stored part-local; the "
    "OBJ / GLB hold them in model space when part_transforms_applied is true.  "
    "pivotbook_index = index into the model's pivot-book list (0x53e987).  shadow_id = the "
    "submesh's shadow-hull group (builder 0x544ae4): submeshes of one part and LOD with "
    "the same id above 0 and the b24 flag clear are merged into one stencil-shadow hull "
    "(in_shadow_hull); 0 = in no hull.  primitive = how the buffer's indices are read: "
    "triangle_list, or triangle_strip (engine 0x431206; the OBJ / GLB hold the strip's "
    "triangles)"
)


def _model_tail_meta(header, order="<"):
    """The keys model_meta adds from the header's tail (parse_model_nodes.model_tail),
    only on a model that has them: "animation" (the path of the model's own
    .animation) and "morph_channels"."""
    try:
        import parse_model_nodes as _pmn
    except ImportError:
        return {}
    T = _pmn.model_tail(header, order)
    if T is None:
        return {}
    out = {}
    if T["animation"]:
        out["animation"] = T["animation"]
    if T["morph_channels"]:
        out["morph_channels"] = T["morph_channels"]
        out["morph_channel_note"] = MORPH_CHANNEL_NOTE
    return out


#: what <name>.model.json says about "morph_channels"
MORPH_CHANNEL_NOTE = (
    "ModelRes morph-channel list (writer 0x543e10, reader 0x547006).  A channel's weight "
    "w > 0 picks the last target whose key <= w and drives it by (w - previous key) / "
    "(key - previous key), the previous key of the first target being 0 (0x4b5b31); "
    "scripts find a channel by its name (Character.GetMorphChannelIdx 0x4bca89).  `target` "
    "keys the per-target weights that code fills (Character+0x244); that it is the index "
    "the stream's morph records carry is inferred.  `f0` is not read by that code"
)


def model_meta(header, model=None, order="<"):
    """Sidecar content of a header-decoded model (decode_model writes it as
    <name>.model.json): LOD count and switch distances, the buffers that are
    NOT exported -- shadow hulls and occluders -- so their presence is on
    record, and (only on a model that has any) its particle emission surfaces.
    A header in the stand-alone Part 1 layout (MODEL_LAYOUTS) carries
    "header_layout": "part1"; the key is absent for the Part 2 layout."""
    M = model or model_header.parse_model_header(header, order)
    if M is None:
        return None
    surfaces = model_header.model_surfaces(header, M, order) or []
    nl = max([len(P["lods"]) for P in M["parts"]] or [0])
    info = model_header.model_lod_info(header, order) or {"lods": []}
    # the stand-alone Part 1 header says so; a Part 2 sidecar is unchanged
    layout = {"header_layout": "part1"} if M.get("layout") == "part1" else {}
    return {
        "format": "watchmen-model-meta/1",
        **layout,
        "lod_count": nl,
        "lods": info["lods"][: max(nl, 1)],
        "lod_note": "LOD i is drawn below max_distance (metres, scaled by the node and "
        "level LOD factors); it fades out over fade_out past it; nothing is drawn past "
        "the last LOD's distance",
        "not_exported": {
            "shadow_hull": sum(len(P["shadow"]) for P in M["parts"]),
            "occluder": sum(1 for P in M["parts"] if P.get("occluder")),
        },
        "parts": _parts_summary(M),
        "parts_note": PARTS_NOTE,
        **_model_tail_meta(header, order),
        **(
            {
                "particle_surfaces": [_surface_summary(s) for s in surfaces],
                "particle_surface_note": "MeshParticleData lists of the nodes (0x561d1c): "
                "the triangles a SurfaceSpawner may emit from.  A triangle is used when its "
                "material_id equals the spawner's materialId (-1 on the spawner: 0x54e23e), "
                "its normal rotated by the Model node has world Y >= faceCullLimit and its "
                "centre lies within the spawner radius in XZ; the budget is "
                "trunc(particleAmount x sum of weights) (0x553c41).  weight = the triangle's "
                "area in m^2 where weight_is_area is true (data); 1.0 per triangle, whatever "
                "the area, where weight_is_unit is true (2 Part 2 and 17 Part 1 surfaces, "
                "2-292 triangles; 8 on nodes named like splash emitter / surface, 2 on other "
                "named nodes, 7 on the unnamed root; why is not established).  Stored normals "
                "are unit length and opposite to the index winding; on Rorschach's arm "
                "surfaces they are 21-36 degrees off the face normal.  The geometry itself is "
                "not exported",
            }
            if surfaces
            else {}
        ),
    }


def model_meta_reduced(header, order="<"):
    """Sidecar content of a model whose header follows NEITHER layout of
    parse_model_header (none in the six shipped sets, as the stand-alone
    Part 1 layout is read too; geometry comes from the descriptor scan): what the
    property bag at the start of the header states -- the LOD switch distances
    and the bag itself -- with the parts that need the full header layout named
    under "not_decoded" instead of being left out silently.  None when the
    property bag does not read exactly (nothing is written then)."""
    bag = model_header.model_property_bag(header, order)
    if bag is None:
        return None
    info = model_header.model_lod_info(header, order) or {"lods": []}
    return {
        "format": "watchmen-model-meta/1",
        "header_decoded": False,
        "record_layout": bag["record_layout"],
        "lod_count": None,
        "lods": info["lods"],
        "lod_note": "LOD i is drawn below max_distance (metres, scaled by the node and "
        "level LOD factors); it fades out over fade_out past it; nothing is drawn past "
        "the last LOD's distance.  These are the header's five distance slots: how many "
        "LODs the model really has is not decoded for this header layout",
        "properties": bag["properties"],
        "not_decoded": [
            "lod_count",
            "not_exported.shadow_hull",
            "not_exported.occluder",
            "particle_surfaces",
        ],
        "not_decoded_note": "this header follows neither known ModelRes layout (Part 2, "
        "stand-alone Part 1), so the engine-exact header path does not read it; the mesh "
        "was found by the descriptor scan",
    }


def model_meta_scanned(header, order="<"):
    """Sidecar of a model whose MESH came from the descriptor scan (the
    header-driven path did not apply: decode_model).  Where the header itself
    follows one of the two header layouts in this byte order it is the full
    model_meta() with "header_decoded": true; otherwise model_meta_reduced().
    "mesh_source": "descriptor scan" marks both."""
    M = model_header.parse_model_header(header, order)
    meta = model_meta(header, M, order) if M is not None else None
    if meta is not None:
        meta["header_decoded"] = True
        # the scan does not know which part a buffer belongs to
        meta["part_transforms_applied"] = False
    else:
        meta = model_meta_reduced(header, order)
    if meta is not None:
        meta["mesh_source"] = "descriptor scan"
    return meta


def _header_model_plan(header, stream, lod, order="<"):
    """Render buffers of the requested LOD with exact stream offsets, or None when
    the engine-exact header path does not apply to this model."""
    if order == ">" and not model_header.console_header_decode():
        return None
    M = model_header.parse_model_header(header, order)
    if M is None or not stream or model_header.model_stream_layout(M, stream, order) is None:
        return None
    bufs = [b for b in model_header.select_model_buffers(M, lod) if b["format"] in (5, 6)]
    if not bufs:
        return None
    return M, bufs


def _model_skipped(log, out_path, reason):
    """decode_model's "nothing written" result, with the reason in the log."""
    mark = "note:" if reason.startswith("empty stream") else "WARNING:"
    log("      %s model %s: not decoded: %s" % (mark, out_path.name, reason))
    return False


def decode_model(
    header,
    stream,
    out_path,
    tex_index=None,
    log=None,
    order=None,
    lod=0,
    status=None,
    stored_name=None,
    glb=None,
):
    """Per-submesh OBJ (+ .mtl linking the diffuse/normal/specular/glossiness maps
    dumped to textures/), each material named by its texture.

    Models are decoded HEADER-DRIVEN (parse_model_header: every buffer offset
    and the texture-list index of each submesh come from the file) on PC and on
    the consoles, in both header layouts.  `lod` picks the level of detail
    written: 0 (default) = the full-detail mesh, an int = that LOD, 'all' = every
    LOD.  Shadow hulls and per-part proxy slabs are never written.  Anything the
    header path rejects (a header of neither layout, a stream its buffers do not
    tile exactly) takes the descriptor scan: strict VB search, then the single-run
    _pick_vb scan.  With --glb, also emits a rigged + textured .glb for skinned
    (stride-56) character models; header-decoded models get NORMAL, TANGENT,
    COLOR_0 (buffers with the has_color flag) and sheet-driven materials in it,
    and rigid models a static .glb, unless `glb.attrs` is off.  `glb`: the
    --glb switches (GlbOptions); None writes no .glb.

    Nothing is left out silently.  With --glb, a model that gets NO .glb has
    `"glb": {"written": false, "reason": ...}` in its .model.json, and a scan
    decode that found fewer submeshes than the header lists (or could not pair
    its materials) has "submeshes" under `not_decoded`.  `status` (a dict the
    caller passes) receives the same facts for the run summary: "glb" (True /
    False / None without --glb), "glb_reason", "color_not_decoded", "partial".
    `stored_name`: the archive's spelling of a model written under a canonical
    name (--names canonical); it goes into the .model.json as "stored_name".
    An exception leaves with a note naming the model, its sizes, its byte order
    and the console in effect."""
    try:
        return _decode_model(
            header, stream, out_path, tex_index, log, order, lod, status, stored_name, glb
        )
    except Exception as ex:
        ex.add_note(
            "model %s: header %d bytes, stream %d bytes, %s, platform %s"
            % (
                getattr(out_path, "name", out_path),
                len(header or b""),
                len(stream or b""),
                order_name(order or kapow_block.header_order_or_none(header)),
                platform_name(
                    model_mesh.console_platform(), order or kapow_block.header_order_or_none(header)
                ),
            )
        )
        raise


def _decode_model(header, stream, out_path, tex_index, log, order, lod, status, stored_name, glb):
    """decode_model's body."""
    if status is None:
        status = {}  # a caller that wants the facts passes its own dict
    status.clear()
    status.update(glb=None, glb_reason=None, color_not_decoded=False, partial=None)
    if tex_index is None:
        tex_index = {}
    if not callable(log):
        log = lambda *a, **k: None
    ho = order or kapow_block.header_order(header)  # auto: the header states its order
    hplan = _header_model_plan(header, stream, lod, ho or "<")
    if hplan:
        order = ho or "<"
    elif order is None:
        order = ho
    if order is None:
        # header without a readable class name: the order with MORE descriptors
        # (a BE model can throw a stray false-positive LE descriptor, so "LE if
        # non-empty" mis-detects those; a tie -- single-submesh models -- stays LE).
        order = (
            ">"
            if len(model_mesh.find_descriptors(header, ">"))
            > len(model_mesh.find_descriptors(header, "<"))
            else "<"
        )
    be = order == ">"
    part_xf = None
    if hplan:
        descs = [(b["vertex_count"], b["stride"], b["index_bytes"]) for b in hplan[1]]
        part_xf = model_header.model_part_transforms(hplan[0])
    else:
        descs = model_mesh.find_descriptors(header, order)
    V = []
    N = []
    U = []
    T = []
    subs = []
    have_n = True
    have_u = True
    SKIN_I = []
    SKIN_W = []
    have_skin = True
    rig = glb is not None
    didx = []  # descriptor index per emitted sub (for submesh_materials pairing)
    restored = []  # restored content in this model (decode_mesh_vertices)
    if descs:
        off = 0
        for di, (nv, stride, ib) in enumerate(descs):
            hi = len(stream) - nv * stride - ib
            cand = off
            vbo = hplan[1][di]["vb"] if hplan else None
            while vbo is None and cand <= min(off + 65536, hi):
                if (
                    model_mesh.is_finite_float(struct.unpack_from(order + "f", stream, cand)[0])
                    and model_mesh.vb_ok(stream, cand, nv, stride, ib, order)
                    and model_mesh.ib_ok(stream, cand, nv, stride, ib, order)
                ):
                    vbo = cand
                    break
                cand += 1
            if vbo is None:
                # planar-decal fallback (strict scan exhausted)
                cand = off
                while cand <= min(off + 65536, hi):
                    if model_mesh.is_finite_float(
                        struct.unpack_from(order + "f", stream, cand)[0]
                    ) and model_mesh.vb_ok_flat(stream, cand, nv, stride, ib, order):
                        vbo = cand
                        break
                    cand += 1
            if vbo is None:
                continue
            base = len(V)
            _notes = []
            verts, norms, uvs = model_mesh.decode_mesh_vertices(
                stream, vbo, nv, stride, be, restored, _notes
            )
            for _n in _notes:
                log("      note: model %s submesh %d: %s" % (out_path.name, di, _n))
            if part_xf is not None:  # part-local -> model space (not skinned buffers)
                _b = hplan[1][di]
                skinned_fmt = "joints" in model_header.vertex_formats(order).get(_b["format"], {})
                xf = None if skinned_fmt else part_xf[_b["part"]]
                verts = model_header.apply_part_transform(xf, verts)
                norms = model_header.apply_part_transform(xf, norms, point=False)
            if rig:
                # pass the detected byte order: without it decode_skin would use
                # the PC layout, whose stride>=56 gate rejects every console
                # (stride-44) skinned submesh -> no console glb.
                si, sw = glb.rig.decode_skin(stream, vbo, nv, stride, order)
                if si is None:
                    have_skin = False
                else:
                    SKIN_I.append(si)
                    SKIN_W.append(sw)
            tstart = len(T)
            ibo = vbo + nv * stride
            if hplan and hplan[1][di].get("primitive_type", 1) == 0:
                # a triangle strip (engine 0x431206): read as a list it gives wrong faces
                _idx = struct.unpack_from(order + "%dH" % (ib // 2), stream, ibo)
                _tris = model_header.index_triangles(_idx, 0)
            else:
                _tris = [
                    struct.unpack_from(order + "3H", stream, ibo + t * 6) for t in range(ib // 6)
                ]
            for a, b, c in _tris:
                if a < nv and b < nv and c < nv and len({a, b, c}) == 3:
                    T.append((base + a, base + b, base + c))
            V.extend(verts)
            if norms is None:
                have_n = False
            else:
                N.extend(norms)
            if uvs is None:
                have_u = False
            else:
                U.extend(uvs)
            subs.append((base, len(V) - base, tstart, len(T) - tstart, stride))
            didx.append(di)
            off = ibo + ib
    if not T:
        if not stream:  # skeleton-only models and a few empty props: nothing to decode
            return _model_skipped(log, out_path, "empty stream: the model has no mesh data")
        pick = model_mesh.pick_vertex_buffer(stream)
        if pick is None:
            return _model_skipped(
                log,
                out_path,
                "no vertex buffer found (%d descriptor(s) in the header, %d stream bytes)"
                % (len(descs), len(stream)),
            )
        off, stride, be, nv, idx = pick
        if nv < 8:
            return _model_skipped(log, out_path, "the buffer scan found only %d vertices" % nv)
        _notes = []
        verts, norms, uvs = model_mesh.decode_mesh_vertices(
            stream, off, nv, stride, be, None, _notes
        )
        for _n in _notes:
            log("      note: model %s: %s" % (out_path.name, _n))
        ntri = len(idx) // 3
        if ntri == 0:
            return _model_skipped(log, out_path, "the buffer scan found no triangles")
        V = verts
        have_n = norms is not None
        have_u = uvs is not None
        N = norms or []
        U = uvs or []
        T = [t for t in itertools.batched(idx[: ntri * 3], 3) if len(set(t)) == 3]
        subs = [(0, len(V), 0, len(T), stride)]
        didx = []  # no descriptors -> no per-submesh material records
    if not T:
        return _model_skipped(log, out_path, "every triangle of the scanned buffer is degenerate")
    mats = material_refs.extract_materials(header)
    materials = None
    if hplan and didx and len(didx) == len(subs):
        # the submesh record carries the index into the model's texture list
        # (FUN_00542541, array at record+0x18)
        tex = hplan[0]["textures"]
        materials = []
        for k in didx:
            ti = hplan[1][k]["tex_index"]
            ok = ti and ti[0] < len(tex)
            materials.append(material_refs.texture_ref(tex[ti[0]]) if ok else "submesh_%d" % k)
    # Per-submesh materialIndex read from the header records: positional
    # pairing is WRONG whenever one material covers several submeshes (see the
    # submesh_materials docstring; Rorschach trenchcoat) -- same pattern as
    # char_lib._parts.  Falls back to positional pairing when the records
    # are unavailable/unparsable (or the _pick_vb path, which has no descriptors).
    if materials is None and mats and didx and len(didx) == len(subs):
        try:
            smat = material_refs.submesh_materials(header, order)
        except Exception:
            smat = []
        if smat:
            materials = [
                (
                    mats[smat[k][1]]
                    if k < len(smat) and smat[k][1] < len(mats)
                    else (mats[k] if k < len(mats) else "submesh_%d" % k)
                )
                for k in didx
            ]
    if materials is None:
        # material list aligns to submeshes in order; when fewer materials than
        # submeshes, assign what we have and leave the remainder as fallback rather
        # than discarding the whole mapping.
        if len(mats) == len(subs):
            materials = mats
        elif 0 < len(mats) < len(subs):
            materials = list(mats) + ["submesh_%d" % k for k in range(len(mats), len(subs))]
        else:
            materials = ["submesh_%d" % k for k in range(len(subs))]
            if mats:
                status["partial"] = (
                    "the header lists %d texture(s) but the scan gave %d submesh(es) and no "
                    "submesh records: no material assigned, the mesh is likely incomplete"
                    % (len(mats), len(subs))
                )
                # more textures than decoded submeshes and no submesh records to pair
                # them: the buffer scan found fewer buffers than the model has
                # (console Palm_Banana_01 / palm_banana_02: 1 of 3).  Say so.
                log(
                    "      WARNING: model %s: no material assigned: the header lists %d textures (%s)"
                    " but %s gave %d submesh(es) and no submesh records, so the pairing is not"
                    " known; the mesh is likely incomplete"
                    % (
                        out_path.name,
                        len(mats),
                        ", ".join(str(m) for m in mats),
                        "the descriptor scan" if didx else "the single-buffer scan",
                        len(subs),
                    )
                )
    obj_mtl.write_obj_mtl(
        out_path,
        out_path.stem,
        V,
        N if have_n else None,
        U if have_u else None,
        T,
        subs,
        materials,
        tex_index,
        log,
    )
    meta = None  # the .model.json content; written after the GLB, whose fate it records
    if hplan and obj_mtl.materials_mode() == "engine":
        try:
            meta = model_meta(header, hplan[0], order)
            meta["part_transforms_applied"] = True
            if order == ">" and model_mesh.console_color_undecoded(
                stream, hplan[0]["buffers"], None, hplan[0].get("layout")
            ):
                status["color_not_decoded"] = True
                meta["not_decoded"] = ["COLOR_0"]
                meta["not_decoded_note"] = (
                    "vertex colours: Xbox 360 and PS3 store the colour bytes in a different "
                    "order, the console of this model is not known (no derived_x360 / "
                    "derived_ps3 source path, WATCHMEN_CONSOLE not set) and its data does "
                    "not show which (console_color_order)"
                )
                log(
                    "      note: model %s: vertex colours not decoded: the console is not "
                    "known and the colour byte order cannot be told from this model "
                    "(set WATCHMEN_CONSOLE=x360 or ps3)" % out_path.name
                )
        except (TypeError, ValueError) as ex:
            meta = None
            log("      ! model meta %s: %s" % (out_path.stem, ex))
    elif obj_mtl.materials_mode() == "engine":
        # scan-decoded model (the header path did not apply): the header, or at
        # least its property bag, still reads
        try:
            meta = model_meta_scanned(header, order)
            if meta is None:
                log(
                    "      WARNING: model meta %s: property bag of the header not readable, "
                    "no .model.json" % out_path.stem
                )
            else:
                # fewer submeshes than the header's full-detail render buffers: the
                # scan missed some (console Palm_Banana_01: 1 of 3)
                M2 = model_header.parse_model_header(header, order)
                want = len(
                    [b for b in model_header.select_model_buffers(M2, 0) if b["format"] in (5, 6)]
                    if M2
                    else []
                )
                if want > len(subs) and not status["partial"]:
                    status["partial"] = (
                        "the header lists %d full-detail render buffer(s), the scan found "
                        "%d submesh(es)" % (want, len(subs))
                    )
                    log(
                        "      WARNING: model %s: incomplete: %s"
                        % (out_path.name, status["partial"])
                    )
                if status["partial"]:
                    meta["not_decoded"] = list(meta.get("not_decoded") or []) + ["submeshes"]
                    meta["submeshes"] = {
                        "decoded": len(subs),
                        "header_render_buffers_lod0": want if M2 else None,
                        "note": status["partial"],
                    }
        except (TypeError, ValueError, struct.error) as ex:
            meta = None
            log("      ! model meta %s: %s" % (out_path.stem, ex))
    log(
        "      model %d verts %d tris %d submeshes%s -> %s"
        % (
            len(V),
            len(T),
            len(subs),
            " +mtl" if any(not m.startswith("submesh_") for m in materials) else "",
            out_path.name,
        )
    )
    # rigged + textured .glb (skinned character models only; bind pose, the
    # model's OWN skeleton: joint names, parents and rest pose from its header --
    # fully file-derived; rig_glb.header_rig)
    skinned = bool(have_skin and SKIN_I and len(SKIN_I) == len(subs))
    # per-vertex attributes need the header-driven decode: its buffers carry the
    # has_color / has_alpha flags and the tangent frame at known offsets
    attrs = None
    if rig and hplan and glb.attrs and didx and len(didx) == len(subs):
        try:
            attrs = glb.rig.mesh_vertex_attributes(header, stream, subs, lod)
        except Exception as ex:
            status["glb_reason"] = "vertex attributes not decoded: %s" % ex
            log("      ! vertex attributes %s: %s" % (out_path.stem, ex))
    if rig and (skinned or attrs is not None):
        try:
            import numpy as _np

            glb_path = out_path.with_suffix(".glb")
            if skinned:
                SI = _np.concatenate(SKIN_I)
                SW = _np.concatenate(SKIN_W)
                # head/accessory -> own palette, static
                _is_body = _model_is_body(header, out_path.name)
                pal = _model_palette(header, out_path.name)
                need = int(SI.max()) + 1 if SI.size else 0
                names = [b["name"] for b in pal["bones"]] if pal else []
                if len(names) < need:
                    names += ["bone_%d" % i for i in range(len(names), need)]
                pal = {"bone_count": len(names), "bones": [{"name": x} for x in names]}
                rig_nodes = None
                if _is_body:
                    try:
                        import parse_model_nodes as _pmn

                        rig_nodes = _pmn.parse(header)
                    except Exception:  # no table: header_rig writes the flat rig and says why
                        rig_nodes = None
            else:  # rigid (or mixed) model: mesh + materials only
                SI = SW = None
                _is_body = False
                rig_nodes = None
                pal = {"bone_count": 0, "bones": []}
            kw = {}
            if attrs is not None:
                kw = dict(
                    normals=attrs["normals"],
                    colors=attrs["colors"],
                    tangents=attrs["tangents"],
                    has_color=attrs["has_color"],
                    has_alpha=attrs["has_alpha"],
                    engine_materials=True,
                )
            glb.rig.build_rigged_glb(
                glb_path,
                _np.asarray(V, float),
                None,
                U if have_u else None,
                SI,
                SW,
                T,
                subs,
                materials,
                tex_index,
                pal,
                None,
                log,
                static=not _is_body,
                tex_size=glb.tex_size,
                nodes=rig_nodes,
                **kw,
            )
            log(
                "      %s glb (%d joints, bind pose) -> %s"
                % ("rigged" if _is_body else "static", pal["bone_count"], glb_path.name)
            )
            status["glb"] = True
        except Exception as ex:
            status["glb_reason"] = "the GLB writer failed: %s" % ex
            log("      ! rig glb %s: %s" % (out_path.stem, ex))
    if rig and not status["glb"]:
        # never silent: say in the sidecar why this model has no .glb
        status["glb"] = False
        if status["glb_reason"] is None:
            if not hplan:
                why = (
                    "the mesh came from the descriptor scan (the header-driven decode did "
                    "not apply) and has no skin: a static GLB is only written from the "
                    "header-driven decode"
                )
            elif not glb.attrs:
                why = "--no-vertex-attrs: only skinned models get a GLB (the 1.3.0 output)"
            elif attrs is None:
                why = "the vertex attributes of the header's buffers could not be paired"
            else:
                why = "not written"
            status["glb_reason"] = why
        if meta is not None:
            meta["glb"] = {"written": False, "reason": status["glb_reason"]}
    if meta is not None:
        if stored_name:
            meta["stored_name"] = stored_name
        if "eyelash_uvs" in restored:
            meta["reconstruction"] = model_mesh.lash_reconstruction_note()
        try:
            import json as _json

            with open(
                out_path.with_suffix(".model.json"), "w", encoding="utf-8", newline="\n"
            ) as _f:
                _json.dump(meta, _f, indent=1)
                _f.write("\n")
        except (OSError, TypeError, ValueError) as ex:
            log("      ! model meta %s: %s" % (out_path.stem, ex))
    return True
