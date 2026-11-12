"""The header of a Texture asset: its image descriptors (format, size, mip count;
`TEX_FMT`, `TEX_ENUMS`), the per-frame layer slots and their labels
(`TEXTURE_SLOTS`, `TEXTURE_SLOT_LABELS`, `texture_layer_label`), animation and
cube-map frames (`parse_texture_frames`, `texture_frame_ms`, `CUBE_FACE_ORDER`),
the alpha flag, and the layer plan that tiles the stream exactly
(`plan_texture_layers`, `chain_bytes`, `chain_bytes_exact`).  One reader:
`read_texture_header` (the header) and `read_descriptor` (the 29-byte descriptor,
also read by `.font` and `.terraincoloringasset`).
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
import byte_reader  # noqa: E402
import extract_log  # noqa: E402
import kapow_block  # noqa: E402


class TextureHeaderError(byte_reader.ReadError):
    """A Texture header that does not read."""


def texture_alpha_flag(header, order="<", name=None):
    """The alpha byte of a Texture header's layer 0 (`u8 hasAlpha` of the image
    descriptor, docs/KAPOW_NAZ_FORMAT.md section 4.2) -> bool, or None when the
    header does not read (read_texture_header) or has no layer 0.  The engine
    copies it to bit 0 of the texture buffer's flags (0x429e77) and the material
    setup enables the alpha test from that bit of the layer-0 texture
    (0x571d5d): the pixels are not inspected.  The same byte on every platform
    (equal to the PC byte on all 908 textures the two Part 2 builds share).  An
    error while reading gives None and a WARNING line naming `name`."""
    try:
        ex = parse_texture_frames(header, order)
        if ex and ex["frames"] and ex["frames"][0]["slots"][0]:
            return bool(ex["frames"][0]["slots"][0]["alpha"])
        return None
    except (struct.error, ValueError, IndexError, KeyError) as e:
        extract_log.warn(
            "      WARNING: texture %s: alpha flag not read, textureHasAlpha left out (%s: %s)"
            % (name or "?", type(e).__name__, e)
        )
        return None


# ---------------------------------------------------------------------------
# Texture header layout: read_texture_header (FUN_005382aa) and read_descriptor
# (FUN_00429e77); docs/KAPOW_NAZ_FORMAT.md section 4.
# ---------------------------------------------------------------------------
TEX_ENUMS = {0, 1, 2, 3, 4, 5, 6, 7, 9, 10}
TEX_FMT = {  # enum -> (D3D name, ('blk',bytes/block) | ('lin',bpp))
    0: ("X8R8G8B8", ("lin", 4)),
    1: ("A8R8G8B8", ("lin", 4)),
    2: ("A8R8G8B8", ("lin", 4)),
    3: ("L8", ("lin", 1)),
    4: ("L8", ("lin", 1)),
    5: ("DXT1", ("blk", 8)),
    6: ("DXT3", ("blk", 16)),
    7: ("DXT5", ("blk", 16)),
    # enum 8 = X360 only (not in TEX_ENUMS, so no PC path accepts it): the engine's
    # format table 0x830892d8 maps id 8 to D3DFORMAT 0x1a20017a = DXT3A, one 4-bit
    # channel in 8-byte blocks.  It is the X360 encoding of the slot-4 L8 map, the
    # HEIGHT map (PC enum 3 in the same slot on all 10 + 23 textures that have one).
    8: ("DXT3A", ("blk", 8)),
    9: ("ATI2", ("blk", 16)),
    # enum 10 = X360's normal-map format: the SAME 2-channel BC5/ATI2 the PC
    # stores under enum 9 (verified: PC-9 -> X360-10 -> PS3-7 across
    # 20 shared textures; BC5 decode of the X360 layer -> clean purple normal
    # coherence 1.3, vs 18.8 as DXT5). PS3 re-encodes the same normal as DXT5(7).
    10: ("ATI2", ("blk", 16)),
}


def is_texture_header(hdr, order="<"):
    return kapow_block.asset_base_class(kapow_block.asset_class(hdr, order)) == "Texture"


#: per-frame layer slots (FUN_005382aa reads slot 0, then 7 x [present][desc]).
TEXTURE_SLOTS = 8
#: file slot -> layer label (read from code: the loader 0x5382aa stores file slot i
#: at frame +4*i; the sheet asks by ENGINE layer through 0x49be2d / 0x4991f0, whose
#: override members are named by the Get...MapOverrideName getters 0x523d0e...).
#: Slots 5 and 6 occur in no shipped texture.
TEXTURE_SLOT_LABELS = {
    0: "diffuse",
    1: "normal",
    2: "specMap",
    3: "glow",
    4: "height",
    5: "fallOff",
    6: "ambOcc",
    7: "specSize",
}
#: engine layer -> file slot (accessors 0x49bcbe...0x49bdff): the renderer counts
#: layers, the file counts slots; layers 0 and 1 are both the diffuse slot
TEXTURE_LAYER_SLOTS = {0: 0, 1: 0, 2: 1, 3: 4, 4: 2, 5: 3, 6: 5, 7: 6, 8: 7}
#: file face k of a cube map = D3D cube face k (0x454384 / 0x454492, LockRect(face, level))
CUBE_FACE_ORDER = ("+X", "-X", "+Y", "-Y", "+Z", "-Z")


def _parse_texture_anim_tail(hdr, p, order="<"):
    """The animation block that follows the frames of a Texture header with
    hasAnim (readers 0x53345a, 0x530639, 0x529337) -> ({"serial", "cycle"}, end).

    Cycle = {"head": [u32 x3], "steps": [{"sub_cycle": bool, "index"}],
    "items": [{"frame_min", "frame_max", "time_min_ms", "time_max_ms", "id"}],
    "sub_cycles": [Cycle]}.  A step that is not a sub-cycle plays item `index`: a
    random frame in [frame_min, frame_max] for a random time in [time_min_ms,
    time_max_ms] ms (0x52929b, 0x5292bb).  The name `id` is inferred (the code
    only stores it).  Raises TextureHeaderError when it does not read."""
    r = byte_reader.ByteReader(hdr, order, TextureHeaderError)
    r.p = p

    def cycle(depth):
        if depth > 8:
            raise TextureHeaderError("cycle depth")
        c = {"head": [r.u32(), r.u32(), r.u32()]}
        c["steps"] = [{"sub_cycle": bool(r.u32()), "index": r.u32()} for _ in range(r.count(8))]
        c["items"] = [
            dict(
                zip(
                    ("frame_min", "frame_max", "time_min_ms", "time_max_ms", "id"),
                    vals,
                    strict=True,
                )
            )
            for vals in ([r.u32() for _ in range(5)] for _ in range(r.count(20)))
        ]
        c["sub_cycles"] = [cycle(depth + 1) for _ in range(r.count(20))]
        return c

    serial = r.u32()
    return {"serial": serial, "cycle": cycle(0)}, r.p


def texture_frame_ms(anim_tail, frames):
    """Display time of each frame in ms, [int | None] * frames, from a
    parse_texture_frames "anim_tail": a frame gets a time only where an item of
    the top cycle shows exactly that frame (frame_min == frame_max) for a fixed
    time (time_min_ms == time_max_ms); None otherwise."""
    out = [None] * frames
    for it in ((anim_tail or {}).get("cycle") or {}).get("items") or []:
        if it["frame_min"] == it["frame_max"] and it["time_min_ms"] == it["time_max_ms"]:
            if it["frame_min"] < frames and out[it["frame_min"]] is None:
                out[it["frame_min"]] = it["time_min_ms"]
    return out


_TEX_DESC = 29  # FUN_00429e77: u32 w, h, format, usage, type; u8 alpha; u32 mips, size


def chain_bytes_exact(en, w, h, mip):
    """Stored bytes of one mip chain.  Block formats as usual; LINEAR formats keep
    every row padded to 4 bytes (the locked D3D pitch), which only shows on the
    1- and 2-texel-wide L8 mips (validated: 936/936 Part 2 PC streams exact)."""
    k, unit = TEX_FMT[en][1]
    total = 0
    for i in range(mip):
        ww, hh = max(1, w >> i), max(1, h >> i)
        if k == "blk":
            total += max(1, (ww + 3) // 4) * max(1, (hh + 3) // 4) * unit
        else:
            total += ((ww * unit + 3) & ~3) * hh
    return total


def read_descriptor(data, offset=0, order="<"):
    """The 29-byte texture descriptor at `offset` (FUN_00429e77): u32 width,
    height, format enum, usage, type; u8 alpha; u32 mips, size -> dict with
    those names (`alpha` the raw byte).  `usage` is TextureBuffer +0x10
    (0x456d46).  `size` is 0 on PC and PS3; on Xbox 360 the stored byte size of
    the layer (all mips; all six faces of a cube).  Read in every Texture
    header frame slot, in `.font` assets and in `.terraincoloringasset`
    headers.  Raises TextureHeaderError when the record runs past the data."""
    if offset < 0 or offset + _TEX_DESC > len(data):
        raise TextureHeaderError(
            "texture descriptor at %d runs past %d bytes" % (offset, len(data))
        )
    w, h, en, usage, typ, alpha, mips, size = struct.unpack_from(order + "5IBII", data, offset)
    return {
        "width": w,
        "height": h,
        "enum": en,
        "usage": usage,
        "type": typ,
        "alpha": alpha,
        "mips": mips,
        "size": size,
    }


def pack_descriptor(d, order="<"):
    """The 29 bytes of a read_descriptor() dict (`alpha` a bool or the byte)."""
    return struct.pack(
        order + "5IBII",
        d["width"],
        d["height"],
        d["enum"],
        d["usage"],
        d["type"],
        int(d["alpha"]),
        d["mips"],
        d["size"],
    )


def descriptor_ok(d):
    """A descriptor the loaders accept: 1..8192 texels each way, type 1 (2D) or 2
    (cube), alpha 0 or 1, 1..14 mips.  The format enum is the caller's test."""
    return (
        0 < d["width"] <= 8192
        and 0 < d["height"] <= 8192
        and d["type"] in (1, 2)
        and d["alpha"] <= 1
        and 1 <= d["mips"] <= 14
    )


def layer_bytes(desc, order, data, offset=0):
    """Stored bytes of the one layer of `desc` that starts at data[offset]: PC
    (order '<') the full mip chain, linear rows padded to 4 bytes
    (chain_bytes_exact); Xbox 360 (big-endian, `size` set) the descriptor's
    `size`; PS3 (big-endian, `size` 0) a 36-byte RSX descriptor whose u32 at +8
    is the byte count of the chain that follows, plus those bytes.  Raises
    TextureHeaderError for a PC format enum without a size rule or a PS3 RSX
    descriptor past the data."""
    if order == "<":
        if desc["enum"] not in TEX_FMT:
            raise TextureHeaderError("texture format id %d" % desc["enum"])
        return chain_bytes_exact(desc["enum"], desc["width"], desc["height"], desc["mips"])
    if desc["size"]:
        return desc["size"]
    if offset + 36 > len(data):
        raise TextureHeaderError("truncated RSX descriptor")
    (n,) = struct.unpack_from(">I", data, offset + 8)
    return 36 + n


def read_texture_header(hdr, order="<"):
    """ENGINE-EXACT Texture header (FUN_005382aa / FUN_00429e77) on ByteReader;
    TextureHeaderError when `hdr` does not read as one.
    order '<' PC / '>' X360 + PS3: the same fields, big-endian (all 937 + 1,190
    headers of each console set parse to the end of the source path).

    [bag][u32 nFrames][u8 hasAnim] then per frame: slot-0 descriptor, 7 x
    ([u8 present][descriptor if present]), [u32 len][source path]; with hasAnim
    the animation block follows (_parse_texture_anim_tail).  Returns
    {"frames": [{"slots": [desc|None]*8, "path": str}], "anim": bool, "anim_tail":
    {"serial", "cycle"} | None, "end": off (past the animation block when it read)};
    desc = {slot, enum, aw, ah, mip, type (1=2D, 2=cube), alpha, usage, drift, size}.
    `usage` is TextureBuffer +0x10 (0x456d46): 0 in block textures.
    `size` is the descriptor's last u32: 0 on PC and PS3; on X360 the STORED
    byte size of the layer (all mips; all six faces of a cube) -- the sizes of a
    header add up to the stream length on 937/937 and 1,190/1,190 textures."""
    if not is_texture_header(hdr, order):
        raise TextureHeaderError("not a Texture header")
    enums = TEX_ENUMS if order == "<" else TEX_FMT
    r = byte_reader.ByteReader(hdr, order, TextureHeaderError)
    r.skip(r.u32())  # type name
    r.skip(4 * r.u32())  # FUN_00511f96: bag = nd dwords
    nf = r.u32()
    anim = r.u8()
    if not 1 <= nf <= 1024 or anim > 1:
        raise TextureHeaderError("%d frames, hasAnim %d" % (nf, anim))
    frames = []
    for _ in range(nf):
        slots = []
        for k in range(TEXTURE_SLOTS):
            if k:
                present = r.u8()
                if present > 1:
                    raise TextureHeaderError("slot %d: present byte %d" % (k, present))
                if not present:
                    slots.append(None)
                    continue
            d = read_descriptor(hdr, r.p, order)
            r.skip(_TEX_DESC)
            if d["enum"] not in enums or not descriptor_ok(d):
                raise TextureHeaderError("slot %d: descriptor %r" % (k, d))
            slots.append(
                {
                    "slot": k,
                    "enum": d["enum"],
                    "fmt": TEX_FMT[d["enum"]][0],
                    "aw": d["width"],
                    "ah": d["height"],
                    "mip": d["mips"],
                    "type": d["type"],
                    "alpha": bool(d["alpha"]),
                    "usage": d["usage"],
                    # slot 7 is the specSize map ("drift": the name the
                    # format rule of texture_layer_label reads)
                    "drift": k == 7,
                    "chain": chain_bytes_exact(d["enum"], d["width"], d["height"], d["mips"]),
                    "size": d["size"],
                }
            )
        sl = r.u32()
        if sl > 1024 or r.p + sl > len(hdr):
            raise TextureHeaderError("source path of %d bytes" % sl)
        path = hdr[r.p : r.p + sl].split(b"\0", 1)[0].decode("latin1")
        r.p += sl
        frames.append({"slots": slots, "path": path})
    p = r.p
    tail = None
    if anim:
        try:
            tail, p = _parse_texture_anim_tail(hdr, p, order)
        except (struct.error, ValueError, RecursionError):
            tail = None  # the frames stand; the block is reported as not read
    return {"frames": frames, "anim": bool(anim), "anim_tail": tail, "end": p}


def parse_texture_frames(hdr, order="<"):
    """read_texture_header(hdr, order), or None when it raises TextureHeaderError."""
    try:
        return read_texture_header(hdr, order)
    except TextureHeaderError:
        return None


def _exact_texture_plan(hdr, stream_len):
    """plan_texture_layers() answer straight from the exact header, or None when
    the header does not parse or does not tile the stream byte-for-byte."""
    ex = parse_texture_frames(hdr)
    if not ex:
        return None
    sets = [[d for d in fr["slots"] if d] for fr in ex["frames"]]
    L = sets[0]
    key = lambda ls: [(d["slot"], d["enum"], d["aw"], d["ah"], d["mip"], d["type"]) for d in ls]
    if any(key(x) != key(L) for x in sets[1:]):
        return None
    cube = any(d["type"] == 2 for d in L)
    if cube and (len(L) != 1 or len(sets) != 1):
        return None  # layer order inside a multi-layer cube is not established
    S = sum(d["chain"] for d in L)
    count = 6 if cube else len(sets)
    if S * count != stream_len:
        return None
    kind = "cube" if cube else ("anim" if count > 1 else "single")
    return {"kind": kind, "layers": L, "count": count, "exact": True}


def is_normal_layer(images, idx, order="<"):
    """Format-agnostic normal-map test. PC normals are ATI2 (enum 9). Consoles
    re-encode the SAME normal: X360 -> enum 10 (BC5), PS3 -> enum 7 (DXT5). On
    PS3 enum 7 is also the diffuse format, but enum 7 only ever appears as
    diffuse (idx 0) on PC, so a non-idx0 DXT5 layer on console is a normal
    (spec/glow are always DXT1/L8). Verified across 20 shared PC/console
    textures."""
    en = images[idx]["enum"]
    if en in (9, 10):
        return True
    if order == ">" and en == 7 and idx > 0:
        return True
    return False


def texture_layer_label(images, idx, order="<"):
    """Layer -> label (the name in the PNG file name and the key the material
    writers look layers up by).

    A layer that knows its FILE SLOT (parse_texture_frames descriptors: every
    header the exact parse reads, all platforms) is labelled by the slot,
    TEXTURE_SLOT_LABELS: 0 diffuse, 1 normal, 2 specMap, 3 glow, 4 height (the
    parallax map; L8, DXT3A on X360), 5 fallOff, 6 ambOcc, 7 specSize (the
    specular-power map; L8, DXT1 on X360).

    Without a slot (a layer list built from formats only) the format rule
    applies: idx0 => diffuse; normal by format; a
    `drift` record or L8 => specSize; the FIRST colour layer after the normal =>
    specMap; a further colour layer => glow.  That rule cannot tell a slot-4
    height map from a slot-7 specSize map, nor a glow map without a specular map
    from a specular map."""
    if isinstance(images[idx], dict) and images[idx].get("slot") in TEXTURE_SLOT_LABELS:
        return TEXTURE_SLOT_LABELS[images[idx]["slot"]]
    if is_normal_layer(images, idx, order):
        return "normal"
    if idx == 0:
        return "diffuse"
    if isinstance(images[idx], dict) and images[idx].get("drift"):
        return "specSize"  # drifted record = specSize slot (any codec)
    if images[idx]["enum"] in (3, 4, 8):  # L8 (X360: DXT3A) -> specular size / power
        return "specSize"
    # A colour layer at idx>0: the FIRST colour layer after the diffuse (layer 0)
    # is the specMap; any further colour layer is glow. Normal layers are skipped.
    prior_colors = sum(
        1
        for k in range(1, idx)
        if not is_normal_layer(images, k, order) and images[k]["enum"] in (0, 1, 2, 5, 6, 7)
    )
    return "specMap" if prior_colors == 0 else "glow"


# ---------------------------------------------------------------------------
# Layer plan: the layers of the header tile the stream once (a single set), six
# times (a cube map) or once per frame (an animation); see _exact_texture_plan.
# ---------------------------------------------------------------------------
def chain_bytes(en, w, h, mip):
    """Sum of `mip` mip-level byte sizes from authored base dims, per format."""
    _, kind = TEX_FMT[en]
    k, unit = kind
    total = 0
    for _ in range(mip):
        if k == "blk":
            total += max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * unit
        else:
            total += max(1, w) * max(1, h) * unit
        if w == 1 and h == 1:
            break
        w = max(1, w >> 1)
        h = max(1, h >> 1)
    return total


def plan_texture_layers(hdr, stream_len):
    """Return dict(kind, layers, count, exact) where kind in {'single','cube',
    'anim'} and Sum(layer chains) * count == stream_len, from the exact header
    (_exact_texture_plan); {'kind': 'fail', 'layers': [], 'count': 0} when the
    header does not read or its layers do not tile the stream.
      single: one material, layers = [diffuse, normal, spec, ...]
      cube  : count == 6, layers describe ONE face
      anim  : count == N frames, layers describe ONE frame (a full material set)
    """
    return _exact_texture_plan(hdr, stream_len) or {"kind": "fail", "layers": [], "count": 0}


def source_name(ex):
    """The asset name of a read_texture_header result: the file name of the
    frame-0 source path without its extension ('' without a path)."""
    path = ex["frames"][0]["path"] if ex and ex["frames"] else ""
    return path.replace("\\", "/").rstrip("/").split("/")[-1].rsplit(".", 1)[0] if path else ""
