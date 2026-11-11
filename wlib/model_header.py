"""The ModelRes header: the vertex formats and strides (`VERTEX_STRIDES`,
`VERTEX_FORMATS`; console `CONSOLE_VERTEX_STRIDES` / `CONSOLE_VERTEX_FORMATS`,
`console_header_decode`), one MeshBuffer record (`read_meshbuffer`) and its
triangles (`index_triangles`, `PRIMITIVE_NAMES`), the header in both layouts
(`parse_model_header`, `MODEL_LAYOUTS`, `model_header_layout_hint`) and the
stream it describes (`model_stream_layout`), the property bag and the LOD
switch distances (`model_property_bag`, `model_lod_info`, `check_lod` /
`model_lod_arg`), particle emission surfaces (`model_surfaces`), the buffers a
decode takes (`select_model_buffers`, `BUFFER_KINDS`), and the part transforms
(`model_part_transforms`, `apply_part_transform`).

  MODEL    interleaved vertex buffer (pos f32 + normal + RGBA8 + uv f16 + tan/bitan),
           stride 44 (rigid) / 56 (skinned), then a u16 triangle-list index buffer.
"""

import os
import struct
import sys

# the flat wlib modules import each other by name (`import kapow_props`); one path
# setup for this module, also when it is run as a script or loaded by file path.
# Append, never insert(0): flat module names must not shadow the stdlib.
_WLIB = os.path.dirname(os.path.abspath(__file__))
if _WLIB not in sys.path:
    sys.path.append(_WLIB)
from wutil import qrows_conj_xyzw  # noqa: E402
import byte_reader  # noqa: E402
import kapow_block  # noqa: E402


# ---------------------------------------------------------------------------
# ENGINE-EXACT ModelRes header (PC).  Reader chain, all read from the exe:
#   FUN_00547006 ModelRes::Read -> FUN_00545927 (part / pivot node)
#   -> FUN_00542541 (submesh record) -> FUN_004336ec (MeshBuffer header).
# The stream blob then holds, per MeshBuffer in header order, the bulk fields in
# the order FUN_00433ef4 reads them: vertices, indices, cluster table, lists,
# optional per-vertex array.  Every offset is computed -- nothing is searched.
# ---------------------------------------------------------------------------
#: vertex stride per format id (exe table 0x00C791B0); the id is the third u32
#: of the vertex-buffer descriptor and selects the D3D9 declaration (FUN_0045544e).
VERTEX_STRIDES = (28, 24, 68, 16, 56, 44, 56, 60, 48, 20, 32)
#: byte offsets of the elements of the formats ModelRes files use.
#:   normal/tangent/bitangent = half3 (+1 unused half), uv = half2,
#:   color = D3DCOLOR (bytes B,G,R,A), joints = D3DCOLOR (idx0..3 = bytes 2,1,0,3),
#:   weights = half4.  Writers: FUN_00430efe (5), FUN_0043106f (6),
#:   FUN_0043114e (9), FUN_00431195 (10).
VERTEX_FORMATS = {
    5: {"position": 0, "normal": 12, "color": 20, "uv": 24, "tangent": 28, "bitangent": 36},
    6: {
        "position": 0,
        "normal": 12,
        "color": 20,
        "uv": 24,
        "tangent": 28,
        "bitangent": 36,
        "joints": 44,
        "weights": 48,
    },
    9: {"position": 0, "normal": 12},  # rigid shadow hull
    10: {"position": 0, "normal": 12, "joints": 20, "weights": 24},  # skinned shadow hull
}
#: the same two tables for the big-endian console files (Xbox 360 and PS3, both
#: parts).  Strides: Xbox 360 exe table 0x8308b6e0; with them (and the console
#: cluster / list record sizes below) the stream blob of every console model of
#: the four console sets is consumed exactly.  Element offsets: read from data
#: against the PC copy of the same vertex (normal, colour, uv, tangent frame,
#: skin).  normal / tangent / bitangent = one packed u32 each (_dec1110), uv =
#: half2, joints = u32 (idx0..3 = bytes 1,2,3,0), weights = half4.  color: four
#: bytes A,R,G,B on Xbox 360 and R,G,B,A on PS3 -- the one field the two
#: consoles store differently (console_color_order).
#: Xbox 360: the streams are read into the GPU buffer unconverted -- the
#: vertex / index buffer code of the image (0x82a30000-0x82a38800) contains no
#: D3D pack or unpack instruction (measured with the VMX128 language,
#: tools/ghidra/README.md "Further tooling").
CONSOLE_VERTEX_STRIDES = (28, 24, 68, 16, 56, 32, 44, 60, 36, 16, 28)
CONSOLE_VERTEX_FORMATS = {
    5: {"position": 0, "normal": 12, "color": 16, "uv": 20, "tangent": 24, "bitangent": 28},
    6: {
        "position": 0,
        "normal": 12,
        "color": 16,
        "uv": 20,
        "tangent": 24,
        "bitangent": 28,
        "joints": 32,
        "weights": 36,
    },
    9: {"position": 0, "normal": 12},  # rigid shadow hull
    # skinned shadow hull; joints bytes 17,18,19,16 (measured against PC; PS3 shader indices.yzwx)
    10: {"position": 0, "normal": 12, "joints": 16, "weights": 20},
}
#: bytes of one cluster record / one item of the per-buffer lists in the stream
#: blob, PC and console (data: the only sizes that tile the console streams)
_STREAM_RECORDS = {"<": (40, 0x44), ">": (48, 0x50)}
_VOLUME_FLOATS = {5: 3, 6: 1, 7: 2}  # box / sphere / capsule (FUN_00524b23)


def console_header_decode():
    """False when WATCHMEN_CONSOLE_MODELS=scan: console (big-endian) models are
    then decoded by the descriptor scan, not from their header.  Default:
    header-driven."""
    return os.environ.get("WATCHMEN_CONSOLE_MODELS", "header").strip().lower() != "scan"


def vertex_strides(order="<"):
    """Vertex stride per format id for a byte order ("<" PC, ">" console)."""
    return CONSOLE_VERTEX_STRIDES if order == ">" else VERTEX_STRIDES


def vertex_formats(order="<"):
    """Element offsets per format id for a byte order ("<" PC, ">" console)."""
    return CONSOLE_VERTEX_FORMATS if order == ">" else VERTEX_FORMATS


def read_meshbuffer(r):
    """MeshBuffer header, FUN_004336ec."""
    # two corners of the buffer's box (minimum, then maximum), not centre / half extent
    m = {"bbox_min": r.floats(3), "bbox_max": r.floats(3)}
    m["has_color"] = r.u8()  # source flag bit 1 (builder 0x0043426c)
    m["has_alpha"] = r.u8()  # source flag bit 2
    if r.boolean():  # FUN_0042f9c1: cloth / physics side arrays
        r.u8()
        for sz in (12, 2, 12, 2, 2):
            r.skip(r.count(sz) * sz)
    m["vertex_flags"], m["vertex_count"], m["format"] = r.u32(), r.u32(), r.u32()
    m["index_flags"], m["index_bytes"], m["ix"] = r.u32(), r.u32(), r.u32()
    # the last u32 is the primitive type: 0 triangle strip, 1 triangle list (table 0xc7f398)
    m["primitive_type"] = m["ix"]
    if m["format"] >= len(VERTEX_STRIDES) or m["index_bytes"] % 2:
        raise ValueError("vertex format %d" % m["format"])
    return m


#: MeshBuffer primitive type -> name in <model>.model.json (engine table 0xc7f398 maps
#: 0..5 to D3D 5, 4, 6, 1, 2, 3; only 0 and 1 occur in the shipped models)
PRIMITIVE_NAMES = {0: "triangle_strip", 1: "triangle_list"}


def index_triangles(idx, primitive_type):
    """Triangles of an index run: 1 = list, 0 = strip (engine 0x431206: (i, i+1, i+2)
    for even i, (i+2, i+1, i) for odd i); the toolkit leaves out a strip triangle that
    repeats an index."""
    if primitive_type == 1:
        return [idx[i : i + 3] for i in range(0, len(idx) - 2, 3)]
    if primitive_type != 0:
        raise ValueError("primitive type %d" % primitive_type)
    out = []
    for i in range(len(idx) - 2):
        t = (idx[i], idx[i + 1], idx[i + 2]) if i % 2 == 0 else (idx[i + 2], idx[i + 1], idx[i])
        if len(set(t)) == 3:
            out.append(t)
    return out


def _mr_part(r, pi, buffers, layout="part2"):
    """Part / pivot node, FUN_00545927; submesh records FUN_00542541.  layout
    "part1": the submesh record of the stand-alone Part 1 build, which has no
    fifth flag byte (MODEL_LAYOUTS)."""
    P = {"pos": r.floats(3), "quat": r.floats(4), "name": r.string()}
    P["f1"], P["parent"] = r.u32(), r.u32()
    # f1 = index into the model's pivot-book list (0x53e987; model+0x9c)
    P["pivotbook_index"] = P["f1"]
    P["lods"] = []
    for li in range(r.count(4)):
        lod = []
        for si in range(r.count(20)):
            sm = {"name": r.string()}
            sm["tex_index"] = [r.u32() for _ in range(r.count(4))]
            sm["b24"], inline, sm["u28"] = r.boolean(), r.boolean(), r.u32()
            sm["hidden"] = sm["b24"]  # 0x4b3886: a set flag skips the submesh
            # u28 = shadow-hull group id ("shadowID", builder 0x544ae4); 0 = in no hull
            sm["shadow_id"] = sm["u28"]
            sm["dynamic_copy"] = r.boolean()
            sm["no_defer"] = r.boolean() if layout == "part2" else None
            # the fifth bool is "the buffer has a cloth mesh" (writer 0x53f736)
            sm["has_cloth_mesh"] = sm["no_defer"]
            if inline:  # FUN_00433ef4 inline bulk: never seen in shipped data
                raise ValueError("inline mesh buffer")
            mb = read_meshbuffer(r)
            r.skip(r.count())  # cooked physics blob
            sm.update(mb, kind="render", part=pi, lod=li)
            lod.append(sm)
            buffers.append(sm)
        P["lods"].append(lod)
    P["shadow"] = []
    for _ in range(r.count(4)):
        for _ in range(r.count(30)):
            fc, cs = r.boolean(), r.u32()
            mb = read_meshbuffer(r)
            mb.update(kind="shadow", part=pi, lod=None, name="", tex_index=[])
            # 0x544ae4: (0, -1) merged hull; (1, i) hull of cloth submesh i
            mb["from_cloth"] = bool(fc)
            mb["cloth_submesh"] = None if cs == 0xFFFFFFFF else cs
            P["shadow"].append(mb)
            buffers.append(mb)
    P["occluder"] = P["proxy"] = None
    if r.boolean():
        # the part's OCCLUDER mesh for the engine's occlusion culling (0x545927 ->
        # FUN_0053f9a5 "... not supported for occluder"); "proxy" is an alias key
        mb = read_meshbuffer(r)
        mb.update(kind="occluder", part=pi, lod=None, name="", tex_index=[])
        P["occluder"] = P["proxy"] = mb
        buffers.append(mb)
    P["lists_offset"] = r.p  # the two volume lists + the particle-surface list
    for _ in range(2):  # collision volumes (FUN_00524b23) + cooked blob
        for _ in range(r.count(8)):
            t = r.u32()
            r.u32()
            if t in _VOLUME_FLOATS:
                r.floats(_VOLUME_FLOATS[t])
            elif t in (2, 4):
                r.u32()
                r.skip(r.count(12) * 12)
                r.skip(r.count(4) * 4)
            else:
                raise ValueError("volume type %d" % t)
            r.floats(7)
            r.skip(r.count())
    P["surface_count"] = r.count(12)  # MeshParticleData list (FUN_00561d1c)
    for _ in range(P["surface_count"]):
        r.skip(r.count(20) * 20)
        r.skip(r.count(12) * 12)
        r.skip(r.count(4) * 4)
    return P


#: the two ModelRes header layouts.  "part2": Part 2 on every platform and the
#: PS3 Part 1 rebuild.  "part1": the stand-alone Part 1 build (PC, Xbox 360) --
#: the same record stream except that (a) a submesh record has no fifth flag
#: byte (its reader, Xbox 360 Part 1 image 0x828bccc0, reads 1, 1, 4, 1 bytes
#: before the MeshBuffer where Part 2's 0x542541 / 0x828fea68 reads 1, 1, 4, 1, 1)
#: and (b) every property blob holds untyped records (kapow_props.read_records).
MODEL_LAYOUTS = ("part2", "part1")


def model_header_layout_hint(header, order="<"):
    """Which MODEL_LAYOUTS entry the header's own property bag points at:
    "part1" when its records are untyped, "part2" when typed, None when the bag
    does not read (nothing else in the header states the build)."""
    try:
        tlen = struct.unpack_from(order + "I", header, 0)[0]
        if not 2 <= tlen <= 64:
            return None
        p = 4 + tlen
        ndw = struct.unpack_from(order + "I", header, p)[0]
    except struct.error:
        return None
    got = kapow_block.props_module().read_records(header, p + 4, p + 4 + 4 * ndw, order)
    if got is None:
        return None
    return "part1" if got[0] == "untyped" else "part2"


def _parse_model_header_as(header, order, layout):
    try:
        r = byte_reader.ByteReader(header, order)
        M = {"type": r.string()}
        r.skip(r.count(4) * 4)  # property bag: dword count (FUN_00511f96)
        r.u32()
        M["has_skeleton"] = r.boolean()
        # 0x53db65: highest bone index used by part 0 / LOD 0, + 1
        v = r.u32()
        M["skinned_bone_count"] = None if v == 0xFFFFFFFF else v
        # the model carries an .animation of its own (curtains, foliage): its path follows
        # the articulated body (0x547006 -> 0x54292c; parse_model_nodes.model_tail)
        M["has_animation"] = r.boolean()
        r.skip(r.count(32) * 32)
        r.skip(r.count(4) * 4)
        # the model's box as its minimum and maximum corner (it is a little larger than
        # the boxes of the buffers); in no output file
        M["bbox_min"], M["bbox_max"] = r.floats(3), r.floats(3)
        tex = [(r.boolean(), r.string()) for _ in range(r.count(5))]
        M["texture_flags"] = [t[0] for t in tex]
        M["textures"] = [t[1] for t in tex]
        M["pivotbooks"] = [r.string() for _ in range(r.count(4))]
        buffers = []
        M["parts"] = [_mr_part(r, pi, buffers, layout) for pi in range(r.count(40))]
        M["buffers"] = buffers
        M["end"] = r.p  # physics / cloth / animation-event tail follows
        M["layout"] = layout
    except (ValueError, struct.error, IndexError):
        return None
    return M


def parse_model_header(header, order="<", layout=None):
    """ModelRes header -> dict, or None when the blob follows neither header
    layout (truncated data, a foreign blob): callers then fall back to the
    descriptor scan.

    {"type", "textures": [path], "texture_flags", "pivotbooks", "bbox_min",
     "bbox_max", "parts": [{name, pos, quat, f1, parent, lods: [[submesh]],
     shadow: [buf], occluder: buf|None (also under the alias key "proxy"),
     lists_offset, surface_count (see model_surfaces)}],
     "buffers": [buf in STREAM order], "end", "layout"}
    Every buf has kind ('render' | 'shadow' | 'occluder'), part, lod, name,
    tex_index, format, vertex_count, index_bytes, has_color, has_alpha, bbox_min, bbox_max
    (the two corners of the box; these keys are in no output file).

    "layout" is the MODEL_LAYOUTS entry the header was read with.  It is taken
    from the header itself, never from a path: the layout the property bag
    points at (model_header_layout_hint) is tried first, then the other one;
    `layout` restricts the read to one.  A header without any submesh reads the
    same either way and keeps the bag's answer."""
    if kapow_block.asset_base_class(kapow_block.asset_class(header, order)).lower() not in (
        "modelres",
        "model",
    ):
        return None
    if layout is not None:
        return _parse_model_header_as(header, order, layout)
    hint = model_header_layout_hint(header, order) or MODEL_LAYOUTS[0]
    for lay in (hint,) + tuple(x for x in MODEL_LAYOUTS if x != hint):
        M = _parse_model_header_as(header, order, lay)
        if M is not None:
            return M
    return None


def model_stream_layout(model, stream, order="<"):
    """Locate every buffer of `model` (parse_model_header) in the stream blob.
    Adds vb / ib / stride / clusters=(offset, count) to each buffer and returns
    the buffer list, or None unless the layout consumes the stream EXACTLY.
    order ">" (console files): the console vertex strides and the console sizes
    of the cluster and list records (_STREAM_RECORDS)."""
    p, n = 0, len(stream)
    strides = vertex_strides(order)
    cluster, item = _STREAM_RECORDS[">" if order == ">" else "<"]
    try:
        for b in model["buffers"]:
            b["stride"] = strides[b["format"]]
            b["vb"] = p
            p += b["vertex_count"] * b["stride"]
            b["ib"] = p
            p += b["index_bytes"]
            (nc,) = struct.unpack_from(order + "I", stream, p)
            b["clusters"] = (p + 4, nc)
            p += 4 + nc * cluster
            (nl,) = struct.unpack_from(order + "I", stream, p)
            p += 4
            for _ in range(nl):
                p += 8 + struct.unpack_from(order + "I", stream, p + 4)[0] * item
            if p >= n:
                return None
            if stream[p] > 1:
                return None
            p += 1 + (b["vertex_count"] * 8 if stream[p] else 0)
            if p > n:
                return None
    except struct.error:
        return None
    return model["buffers"] if p == n else None


def check_lod(lod):
    """`lod` as decode_model / select_model_buffers accept it: 'all' / None or an
    int >= 0.  ValueError otherwise (a negative LOD would select no buffer and
    silently drop the model onto the descriptor scan)."""
    if lod in (None, "all"):
        return lod
    if isinstance(lod, bool) or not isinstance(lod, int) or lod < 0:
        raise ValueError("model LOD must be a whole number >= 0 or 'all', not %r" % (lod,))
    return lod


def model_lod_arg(v):
    import argparse

    try:
        return check_lod(v if v == "all" else int(v))
    except ValueError:
        raise argparse.ArgumentTypeError("expected a whole number >= 0 or 'all', got %r" % v)  # noqa: B904


#: buffer kinds of a model: "render" (drawn), "shadow" (stencil shadow-volume hull,
#: vertex formats 9 / 10, REShadowVolume), "occluder" (occlusion-culling mesh).
#: Only "render" is ever exported as visible geometry.
BUFFER_KINDS = ("render", "shadow", "occluder")
BUFFER_KIND_ALIASES = {"proxy": "occluder", "shadow_hull": "shadow"}
#: what a non-render kind is (decode_model_mesh submesh "role")
BUFFER_ROLES = {"render": "render", "shadow": "shadow_hull", "occluder": "occluder"}
_LOD_PAIRS = ("01", "12", "23", "34", "45")


def model_property_bag(header, order="<"):
    """The property bag at the start of a ModelRes header -- `[u32 len][type
    name][u32 dwords][records]` (reader 0x511f96) -- in either record layout ->
    {"record_layout": "typed" | "untyped", "records": kapow_props.read_records
    tuples, "properties": {name: value}} or None when the records do not read
    exactly to the stored dword count.  A property whose type is not known is
    listed as {"hex": ...}."""
    kp = kapow_block.props_module()
    try:
        tlen = struct.unpack_from(order + "I", header, 0)[0]
        if not 2 <= tlen <= 64:
            return None
        p = 4 + tlen
        ndw = struct.unpack_from(order + "I", header, p)[0]
    except struct.error:
        return None
    got = kp.read_records(header, p + 4, p + 4 + 4 * ndw, order)
    if got is None:
        return None
    names, ut, props = kp.namedict(), kp.untyped_types(), {}
    for _o, key, th, q, k in got[1]:
        if th is None:
            tn = ut.get(key)
        else:
            tn = "id" if th == kp.T_UNIQUE_ID else kp.TYPES.get(th)
        val = kp.record_value(tn, header, q, k, order)
        if isinstance(val, float):
            val = round(val, 6)
        elif val is None:
            val = {"hex": header[q : q + 4 * k].hex()}
        props.setdefault(names.get(key) or "%08x" % key, val)
    return {"record_layout": got[0], "records": got[1], "properties": props}


def model_lod_info(header, order="<"):
    """LOD switch distances of a ModelRes header's property bag (lodDistance01..45,
    lodFadeIn.., lodFadeOut..; ModelRes::vfunc_06 0x53ef10) -> {"lods": [{"lod": i,
    "max_distance", "fade_in", "fade_out"}], "store_lowest_lod_in_header"} or None.

    The engine (FUN_0053a317) draws LOD i while the scaled camera distance is below
    max_distance[i]; LOD i-1 keeps fading out for fade_out[i-1] metres past its own
    limit and LOD i+1 fades in over the last fade_in[i] metres (alpha blended, no
    hysteresis); past the last LOD's distance the model is not drawn.  Distance =
    distance to the bounds minus the bounding radius, times the node's
    geometryLodFactor and the level's globalGeometryLodFactor."""
    try:
        tlen = struct.unpack_from(order + "I", header, 0)[0]
        p = 4 + tlen + 4
        end = kapow_block.propbag_end(header, order)
        num = kapow_block._name_hash("number")
        want = {}
        for pair in _LOD_PAIRS:
            for key in ("lodDistance", "lodFadeIn", "lodFadeOut"):
                want[kapow_block._name_hash(key + pair)] = (key, pair)
        want[kapow_block._name_hash("storeLowestLODInHeader")] = ("store", "")
        got = {}
        bag = model_property_bag(header, order)
        if bag is not None:
            # exact walk of the bag in either record layout.  (The fixed 20-byte
            # stride below loses its place on a string longer than one dword: a
            # model with an `animation` path -- 22 in PC Part 2 -- would get no LODs.)
            num_ok = (None, num)
            for _o, lo, th, q, k in bag["records"]:
                if lo in want and k == 1:
                    key = want[lo]
                    if key[0] == "store":
                        got[key] = bool(struct.unpack_from(order + "I", header, q)[0])
                    elif th in num_ok:
                        got[key] = struct.unpack_from(order + "f", header, q)[0]
            p = end
        while p + 20 <= end:
            _salt, lo, hi, tag, val = struct.unpack_from(order + "5I", header, p)
            if lo in want:
                key = want[lo]
                if key[0] == "store":
                    got[key] = bool(val)
                elif hi == num:
                    got[key] = struct.unpack_from(order + "f", header, p + 16)[0]
            p += 24 if tag == 2 else 20
    except (struct.error, IndexError):
        return None
    if not any(k[0] == "lodDistance" for k in got):
        return None
    lods = []
    for i, pair in enumerate(_LOD_PAIRS):
        if ("lodDistance", pair) not in got:
            break
        lods.append(
            {
                "lod": i,
                "max_distance": round(got[("lodDistance", pair)], 4),
                "fade_in": round(got.get(("lodFadeIn", pair), 0.0), 4),
                "fade_out": round(got.get(("lodFadeOut", pair), 0.0), 4),
            }
        )
    return {"lods": lods, "store_lowest_lod_in_header": got.get(("store", ""))}


def model_surfaces(header, model=None, order="<"):
    """Particle emission surfaces of a header-decoded model, mesh nodes included
    (node+0x64 list of MeshParticleData, reader 0x561d1c; consumer SurfaceSpawner
    0x54fc6b / 0x54decc) -> [{"part", "node", "surface", ... the dict of
    skeleton_records.parse_volume_lists: class, tris [{normal, area_weight,
    material_id}], verts, indices, weight_sum, weight_is_area}] in file order,
    or None when the header does not follow the Part 2 layout."""
    M = model or parse_model_header(header, order)
    if M is None:
        return None
    import skeleton_records as _sr

    out = []
    for pi, P in enumerate(M["parts"]):
        if not P.get("surface_count"):
            continue
        try:
            _lists, surfaces, _end = _sr.parse_volume_lists(header, P["lists_offset"], order)
        except (ValueError, struct.error):
            return None
        for si, s in enumerate(surfaces):
            out.append(dict(s, part=pi, node=P["name"], surface=si))
    return out


def select_model_buffers(model, lod=0, kinds=("render",)):
    """Buffers of the requested kinds (BUFFER_KINDS; "proxy" is accepted for
    "occluder"), in stream order.  `lod`: an int picks that LOD of every part
    (clamped to the part's last LOD); 'all' / None keeps all."""
    lod = check_lod(lod)
    kinds = tuple(BUFFER_KIND_ALIASES.get(k, k) for k in kinds)
    out = []
    for b in model["buffers"]:
        if b["kind"] not in kinds:
            continue
        if b["kind"] == "render" and lod not in (None, "all"):
            nl = len(model["parts"][b["part"]]["lods"])
            if b["lod"] != min(int(lod), nl - 1):
                continue
        out.append(b)
    return out


def _part_local_matrix(pos, quat):
    """Engine local transform of a part as (3x3 rows, translation): a vector
    rotates as conj(q)·v·q (q = x, y, z, w as stored), then pos is added."""
    return qrows_conj_xyzw(quat), tuple(float(c) for c in pos)


def _part_is_identity(P):
    q = tuple(P["quat"])
    return tuple(P["pos"]) == (0.0, 0.0, 0.0) and q[:3] == (0.0, 0.0, 0.0) and abs(q[3]) == 1.0


def model_part_transforms(model):
    """Model-space transform of every part of a parse_model_header dict:
    [None | (3x3 rows, translation)], None where the whole chain is identity.

    The vertices of a buffer are stored in the space of its part (measured: the
    union of the full-detail submesh boxes equals the model box on every model
    with a moved render part only when each part's vertices are transformed by
    v' = conj(q)·v·q + pos, the part first and then every parent up to parent
    0xFFFFFFFF).  A parent index that is out of range or closes a loop ends the
    chain.  The decoders do not apply it to skinned buffers (a format with
    joints), which the bone palette places; no shipped model has one in a moved
    part."""
    parts = model["parts"]
    out = []
    for pi in range(len(parts)):
        chain, seen, k = [], set(), pi
        while 0 <= k < len(parts) and k not in seen:
            seen.add(k)
            chain.append(parts[k])
            k = parts[k]["parent"]
        if all(_part_is_identity(P) for P in chain):
            out.append(None)
            continue
        M = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        t = (0.0, 0.0, 0.0)
        for P in chain:  # the part itself, then its parents
            m, p = _part_local_matrix(P["pos"], P["quat"])
            M = tuple(
                tuple(sum(m[i][k] * M[k][j] for k in range(3)) for j in range(3)) for i in range(3)
            )
            t = tuple(sum(m[i][k] * t[k] for k in range(3)) + p[i] for i in range(3))
        out.append((M, t))
    return out


def apply_part_transform(xf, vectors, point=True):
    """`vectors` [(x, y, z)] through one model_part_transforms entry: rotated,
    and translated when `point`.  None (identity chain) returns the input."""
    if xf is None or vectors is None:
        return vectors
    M, t = xf
    if not point:
        t = (0.0, 0.0, 0.0)
    (a, b, c), (d, e, f), (g, h, i) = M
    return [
        (a * x + b * y + c * z + t[0], d * x + e * y + f * z + t[1], g * x + h * y + i * z + t[2])
        for x, y, z in vectors
    ]
