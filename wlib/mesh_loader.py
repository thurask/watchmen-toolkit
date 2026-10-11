#!/usr/bin/env python3
"""mesh_loader.py -- the one mesh loader of the character pipeline.

Every character path reads its mesh pieces here: char_lib.load_parts (the
`characters` / `faces` / `charlibs` bodies), variant_glb.load_parts (`char`),
and characters_export's weapon and head attachments (_weapon_attach_parts,
_rigid_attach_parts).  1.4.0 had four hand-synchronised copies of the same
byte search.

Primary path: the model header (watchmen_extract.decode_model_mesh -- the
header parsed by parse_model_header, every buffer located by
model_stream_layout, which must consume the stream exactly).  Each render
buffer of vertex format 5 / 6 is one submesh, at the stream offset the header
gives, its index run read with the buffer's primitive type (a triangle strip
is decoded as a strip, watchmen_extract.index_triangles).  Positions are kept
part-local, as stored (part_space=True), which is what the loaders always used.

Fallback: the descriptor scan of 1.4.0 (find_descriptors, then the first
stream offset where _vb_ok and _ib_ok hold, then char_lib.flat_buffer for a
planar piece), used only for a model whose header path does not apply or for a
geometry descriptor the header does not list -- and every such submesh is
logged ("note: <model> sub<i>: header path not applicable (<why>); scanned").

Nothing is dropped silently:
* a degenerate triangle (an index repeated) is left out, counted and logged
  as a note;
* a triangle that names a vertex the buffer does not have marks the submesh
  not decoded (char_lib.note_dropped, with the reason);
* a palette name (a node of the model) that has no slot in the bind is
  logged, and returned so the caller can state it in the GLB
  (palette_remap; char_lib.dropped_palette_names);
* a skin influence whose joint is outside the model's palette is NOT clamped
  onto another bone: its weight goes to 0 (joint 0) and the vertex's other
  weights are renormalised; a vertex left with no weight marks the part not
  decoded (remap_skin).
"""

import os
import re
import struct
import sys

import numpy as np

from wutil import order_name, platform_name

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)  # append, never insert(0): flat module names must not shadow the stdlib

#: the scan searches this many stream offsets past the end of the previous piece
SCAN_WINDOW = 65536

_CANON_RE = re.compile(r"^Bip\d+\s+")


def _canon(name):
    """A bone name without its 'BipNN ' prefix."""
    return _CANON_RE.sub("", name)


def bind_slotter(bn):
    """name -> slot in the bind's bone list `bn`, or None.  Exact matches win;
    then the 'BipNN '-prefix-insensitive match (2026-07-13: Thug / Heavies
    models say 'RUpArmTwist' where the medium bind says 'Bip02 RUpArmTwist';
    KnotTop_Large says 'Bip01 Attach RHand' where the bind says 'Attach RHand')."""
    uslot = {n: i for i, n in enumerate(bn)}
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

    return _slot


#: where a palette name without a bind slot sits in the model's name list
MID_LIST = "mid-list"
AFTER_LAST = "after the last name with a slot"

#: (model, where, names) of the AFTER_LAST notes palette_remap has logged since
#: the last reset_notes(): a model loaded again (an outfit, an alternative part)
#: does not repeat the note
_NOTED = set()


def reset_notes():
    """Forget the notes logged so far (char_lib.dropped_palette_names(reset=True)
    calls it: once per character GLB)."""
    _NOTED.clear()


def palette_remap(mh, order, bn, name="model", log=print):
    """Skin-index remap of a model for the bind bone list `bn` ->
    (remap, dropped).

    The engine's palette of a skinned piece is the model's node list rotated by
    one (palette index k is node k - 1, index 0 the last node).  Its names are
    taken in file order (extract_skeletons._ordered_names); those without a slot
    in the bind (bind_slotter) are left out before the rotation, as in 1.4.0.
    remap[k] is the bind slot of palette index k (int64 array).

    `dropped`: [{"name", "where"}] for the names that are NODES of the model
    (parse_model_nodes) and have no bind slot, in file order.  "where" is
    MID_LIST when a name with a slot follows it -- the rotate-by-one list is
    shortened there and every palette index after it moves: logged as a warning
    ("! <model>: palette name(s) ... have no bind slot - rotate-by-one list
    shortened") -- or AFTER_LAST, when no index moves but the wrap-around
    palette index 0 (logged as a note; char_lib.skinned_part warns when a
    weighted influence uses index 0, and remap_skin drops an index past the
    shortened list).  On the six game sets the only such name is 'Interact' (the binds
    say 'interact'), always after the last name with a slot, and no weighted
    influence uses palette index 0 (measured).  The other length-prefixed
    strings of the header (piece and part names) are not nodes and are not
    reported."""
    import extract_skeletons as es

    _slot = bind_slotter(bn)
    plist = [x for _, x in es._ordered_names(mh, order)]
    pf = [x for x in plist if _slot(x) is not None]
    ppal = [pf[(k - 1) % len(pf)] for k in range(len(pf))]  # engine rotate-by-one
    remap = np.array([_slot(n) for n in ppal], dtype=np.int64)
    try:
        import parse_model_nodes as pmn

        nodes = set(pmn.parse(mh)[0])
    except Exception:  # a header without a readable node table: report every name
        nodes = None
    last = max([i for i, x in enumerate(plist) if _slot(x) is not None] or [-1])
    dropped, seen = [], set()
    for i, x in enumerate(plist):
        if _slot(x) is None and (nodes is None or x in nodes) and x not in seen:
            seen.add(x)
            dropped.append({"name": x, "where": MID_LIST if i < last else AFTER_LAST})
    if log is not None:
        for where, fmt in (
            (MID_LIST, "  ! %s: palette name%s %s %s no bind slot - rotate-by-one list shortened"),
            (
                AFTER_LAST,
                "  note: %s: palette name%s %s %s no bind slot; %s after every name that has "
                "one, so no palette index moves but the wrap-around index 0",
            ),
        ):
            got = [d["name"] for d in dropped if d["where"] == where]
            key = (name, where, tuple(got))
            if got and where == AFTER_LAST and key in _NOTED:
                continue  # this note once per model (reset_notes); a warning every time
            _NOTED.add(key)
            if got:
                many = len(got) > 1
                args = (name, "s" if many else "", ", ".join(repr(x) for x in got))
                args += ("have" if many else "has",)
                if where == AFTER_LAST:
                    args += ("they come" if many else "it comes",)
                log(fmt % args)
    return remap, dropped


def remap_skin(skidx, skw, remap):
    """Skin of one piece in bind slots -> (SI uint16 (n,4), SW float32 (n,4),
    stats).

    skidx / skw: rig_glb.decode_skin's joint quads (palette indices) and
    weights.  An influence whose palette index is >= len(remap) (the palette has
    no such entry) is not clamped: its joint becomes 0 and its weight 0, and
    the vertex's remaining weights are renormalised (only those vertices change).
    stats: {"oob_influences": weighted influences dropped, "oob_zero_weight":
    influences with weight 0 already, "vertices_changed", "vertices_unweighted":
    vertices left with no weight (the caller marks the piece not decoded),
    "max_index"}."""
    I = np.asarray(skidx, np.int64)
    W = np.asarray(skw, np.float32)
    n = len(remap)
    oob = I >= n
    stats = {
        "oob_influences": int((oob & (W != 0)).sum()),
        "oob_zero_weight": int((oob & (W == 0)).sum()),
        "vertices_changed": 0,
        "vertices_unweighted": 0,
        "max_index": int(I.max()) if I.size else -1,
    }
    if n == 0:
        return (
            np.zeros(I.shape, np.uint16),
            np.zeros(W.shape, np.float32),
            stats | {"vertices_unweighted": int(len(I))},
        )
    SI = remap[np.where(oob, 0, I)]
    if not oob.any():
        return SI.astype(np.uint16), W, stats
    SI = np.where(oob, 0, SI)
    rows = np.nonzero((oob & (W != 0)).any(1))[0]
    W = W.copy()
    W[oob] = 0.0
    if len(rows):
        s = W[rows].sum(1, keepdims=True)
        bad = s[:, 0] < 1e-6
        stats["vertices_changed"] = int(len(rows))
        stats["vertices_unweighted"] = int(bad.sum())
        s[bad] = 1.0
        W[rows] = (W[rows] / s).astype(np.float32)
    return SI.astype(np.uint16), W, stats


class LoadReport(dict):
    """What one load_submeshes call did: counts and the per-submesh path."""

    def __init__(self, model):
        super().__init__(
            model=model,
            submeshes=0,
            header=0,
            scanned=0,
            strips=0,
            degenerate_triangles=0,
            not_decoded=0,
            scan_reasons=[],
        )


def _header_path(mh, ms, order):
    """(watchmen_extract.decode_model_mesh result, None), or (None, why) when the
    header path does not apply to this model."""
    import watchmen_extract as we

    try:
        D = we.decode_model_mesh(mh, ms, lod="all", kinds=("render",), order=order, part_space=True)
    except (ValueError, struct.error, IndexError) as ex:  # a malformed header is data
        return None, "the header does not decode (%s)" % ex
    if D is not None:
        return D, None
    if order == ">" and not we.console_header_decode():
        return None, "WATCHMEN_CONSOLE_MODELS=scan"
    if ms is None:
        return None, "no stream"
    M = we.parse_model_header(mh, order)
    if M is None:
        return None, "the header does not parse as a ModelRes"
    return None, "the header's buffers do not consume the stream exactly"


def _scan_one(ms, off, nv, stride, ib, order):
    """1.4.0's offset search for one descriptor -> (vbo or None, "strict" | "flat")."""
    import watchmen_extract as we
    import char_lib

    hi = len(ms) - nv * stride - ib
    c = off
    while c <= min(off + SCAN_WINDOW, hi):
        # require a CLEAN index buffer too: a false-positive VB (X360
        # TwilightLadyHair / rorschachspots) sits ~4 bytes before the real one,
        # passes _vb_ok, but has a ~50% repeated-index IB.
        if (
            we._sane(struct.unpack_from(order + "f", ms, c)[0])
            and we._vb_ok(ms, c, nv, stride, ib, order)
            and we._ib_ok(ms, c, nv, stride, ib, order)
        ):
            return c, "strict"
        c += 1
    return char_lib.flat_buffer(ms, off, nv, stride, ib, order), "flat"


def load_submeshes(
    mh,
    ms,
    name,
    order=None,
    platform=None,
    fallback_name="sub%d",
    positional=True,
    skin=True,
    attrs=True,
    log=print,
):
    """Decode the render pieces of one .model (header bytes `mh`, stream `ms`)
    -> (subs, report).

    order: "<" / ">" (None: char_lib.model_order).  platform: the console of a
    big-endian model (for the colour order of the attributes).
    fallback_name: the material name of a piece without one ("%d" gets the
    submesh index, or "%s_sub%d" the model name and the index).  positional:
    a piece without a material record takes the header's material list by
    position, as char_lib / variant_glb / the weapon loader do (False: straight
    to fallback_name, as the head loader does).
    skin: decode the joint quads and weights (rig_glb.decode_skin).
    attrs: the header's per-vertex attributes (variant_glb.buffer_vertex_attrs).

    Each sub: {"index", "vertex_count", "stride", "index_bytes", "vb",
    "path" ("header" | "scan" | "flat"), "primitive", "V" (n,3) float64
    as stored, "UV" (n,2) float32 ((0, 0) per vertex when the buffer has none),
    "T" (k,3) int triangles, "material", "attrs" (dict or None), "skin" (joint
    quads uint8, weights float32) or (None, None)}.  A piece that cannot be
    decoded is NOT in `subs`: char_lib.note_dropped records and logs it."""
    import watchmen_extract as we
    import char_lib
    import rig_glb
    import variant_glb as _vg

    rep = LoadReport(name)
    if order is None:
        order = char_lib.model_order(mh, ms, name)
    descs = we.find_descriptors(mh, order)
    D, why = _header_path(mh, ms, order)
    plan = []  # (desc ordinal or None, nv, stride, ib, header submesh or None)
    if D is not None:
        hsubs = [s for s in D["submeshes"] if s["format"] in (5, 6)]
        for s in D["submeshes"]:
            if s["format"] not in (5, 6) and log is not None:
                log(
                    "  note: %s: render buffer %r has vertex format %d, not loaded "
                    "(a character piece is format 5 or 6)" % (name, s["name"], s["format"])
                )
        # The geometry descriptors are the triangle-list buffers of formats 5 / 6,
        # in header order (the order of the stream).  Pair each with the next
        # header buffer of the same size; one the header does not list is
        # scanned for, right after the piece before it.  A header buffer without
        # a descriptor (a triangle strip) is decoded from the header, in its
        # stream place.
        h = 0
        for j, dsc in enumerate(descs):
            m = h
            while m < len(hsubs) and not (
                hsubs[m]["primitive_type"] == 1
                and (hsubs[m]["vertex_count"], hsubs[m]["stride"], hsubs[m]["index_bytes"]) == dsc
            ):
                m += 1
            if m == len(hsubs):
                plan.append((j,) + tuple(dsc) + (None,))
                continue
            for s in hsubs[h:m]:
                plan.append((None, s["vertex_count"], s["stride"], s["index_bytes"], s))
            plan.append((j,) + tuple(dsc) + (hsubs[m],))
            h = m + 1
        for s in hsubs[h:]:
            plan.append((None, s["vertex_count"], s["stride"], s["index_bytes"], s))
    else:
        for j, (nv, st, ib) in enumerate(descs):
            plan.append((j, nv, st, ib, None))
    mats = we.extract_materials(mh)
    smat = we.submesh_materials(mh, order)
    subs = []
    off = 0
    si = None
    try:
        for si, (k, nv, stride, ib, hs) in enumerate(plan):
            rep["submeshes"] += 1
            if hs is not None:
                vbo, path = hs["vb"], "header"
                V = np.array(hs["positions"], float)
                uvs = hs["uvs"]
                restored = hs.get("restored")
                notes = hs.get("not_finite") or []
                idx_tris = hs["triangles"]
                prim = hs.get("primitive") or "primitive type %d" % hs["primitive_type"]
            else:
                reason = why or "the header does not list this buffer"
                vbo, how = _scan_one(ms, off, nv, stride, ib, order)
                rep["scan_reasons"].append(reason)
                if log is not None:
                    log(
                        "  note: %s sub%d: header path not applicable (%s); scanned"
                        % (name, si, reason)
                    )
                if vbo is None:
                    rep["not_decoded"] += 1
                    char_lib.note_dropped(
                        name, si, nv, stride, ib, order, char_lib.NO_BUFFER, log=log
                    )
                    continue
                path = "scan" if how == "strict" else "flat"
                restored, notes = [], []
                v, _, uvs = we._decode_sub(ms, vbo, nv, stride, order == ">", restored, notes)
                V = np.array(v, float)
                ibo = vbo + nv * stride
                idx_tris = [
                    struct.unpack_from(order + "3H", ms, ibo + t * 6) for t in range(ib // 6)
                ]
                prim = "triangle_list"
            off = vbo + nv * stride + ib
            for msg in notes:
                if log is not None:
                    log("  note: %s sub%d: %s" % (name, si, msg))
            if path == "header":
                rep["header"] += 1
            else:
                rep["scanned"] += 1
            if prim == "triangle_strip":
                rep["strips"] += 1
            T = []
            bad = None
            ndeg = 0
            for t in idx_tris:
                x, y, z = t
                if x >= nv or y >= nv or z >= nv:
                    bad = max(x, y, z)
                    break
                if x == y or y == z or x == z:
                    ndeg += 1
                    continue
                T.append((x, y, z))
            rep["degenerate_triangles"] += ndeg
            if ndeg and bad is None and log is not None:
                log(
                    "  note: %s sub%d: %d degenerate triangle%s (an index repeated) left out"
                    % (name, si, ndeg, "" if ndeg == 1 else "s")
                )
            if bad is not None:
                rep["not_decoded"] += 1
                char_lib.note_dropped(
                    name,
                    si,
                    nv,
                    stride,
                    ib,
                    order,
                    "the index buffer names vertex %d of a %d-vertex buffer" % (bad, nv),
                    log=log,
                )
                continue
            if not len(V) or not T:
                rep["not_decoded"] += 1
                char_lib.note_dropped(
                    name, si, nv, stride, ib, order, char_lib.NO_TRIANGLES, log=log
                )
                continue
            if k is not None and k < len(smat) and smat[k][1] < len(mats):
                mat = mats[smat[k][1]]
            elif hs is not None and k is None and hs.get("material") is not None:
                mat = hs["material"]  # a buffer without a descriptor: the header's own record
            elif positional and k is not None and k < len(mats):
                mat = mats[k]
            else:
                mat = fallback_name % ((name, si) if fallback_name.count("%") == 2 else (si,))
            sk = (None, None)
            if skin:
                sk = rig_glb.decode_skin(ms, vbo, nv, stride, order)
            subs.append(
                {
                    "index": si,
                    "vertex_count": nv,
                    "stride": stride,
                    "index_bytes": ib,
                    "vb": vbo,
                    "path": path,
                    "primitive": prim,
                    "V": V,
                    "UV": np.array(uvs if uvs else [(0.0, 0.0)] * len(V), np.float32),
                    "T": np.array(T),
                    "material": mat,
                    "restored": restored or None,
                    "attrs": (
                        _vg.buffer_vertex_attrs(mh, ms, order, vbo, nv, stride, platform)
                        if attrs
                        else None
                    ),
                    "skin": sk,
                }
            )
    except Exception as ex:
        ex.add_note(
            f"mesh_loader: model {name!r} submesh {si} of {len(plan)} ({order_name(order)}, "
            f"platform {platform_name(platform, order)})"
        )
        raise
    return subs, rep
