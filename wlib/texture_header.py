"""The header of a Texture asset: its image descriptors (format, size, mip count;
`TEX_FMT`, `TEX_ENUMS`), the per-frame layer slots and their labels
(`TEXTURE_SLOTS`, `TEXTURE_SLOT_LABELS`, `texture_layer_label`), animation and
cube-map frames (`parse_texture_frames`, `texture_frame_ms`, `CUBE_FACE_ORDER`),
the alpha flag, and the layer plan that tiles the stream exactly
(`plan_texture_layers`, `chain_bytes`, `chain_bytes_exact`).
`parse_texture_header` and its helpers are the descriptor scan the plan falls
back to.
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
    header has no image record.  The engine copies it to bit 0 of the texture
    buffer's flags (0x429e77) and the material setup enables the alpha test from
    that bit of the layer-0 texture (0x571d5d): the pixels are not inspected.
    PC: parse_texture_frames; otherwise the byte at +25 of the 30-byte window
    parse_texture_header uses (the same on X360: equal to the PC byte on all 908
    textures the two Part 2 builds share).  A header the readers refuse gives
    None and a WARNING line naming `name`."""
    try:
        if order == "<":
            ex = parse_texture_frames(header)
            if ex and ex["frames"] and ex["frames"][0]["slots"][0]:
                return bool(ex["frames"][0]["slots"][0]["alpha"])
        info = parse_texture_header(header, order)
        if not info or not info["images"]:
            return None
        return bool(header[info["images"][0]["rec_off"] + 25] & 1)
    except (struct.error, ValueError, IndexError, KeyError) as e:
        extract_log.warn(
            "      WARNING: texture %s: alpha flag not read, textureHasAlpha left out (%s: %s)"
            % (name or "?", type(e).__name__, e)
        )
        return None


# ---------------------------------------------------------------------------
# Texture .header parser  (DETERMINISTIC; no offset scan).
#
# Layout of a "Texture" asset header (the block_h_z blob), all little-endian:
#   +0    u32  typeNameLen           (8 = "Texture\0")
#   +4    char[typeNameLen] typeName ("Texture\0")
#   +12   u32  classId/version       (always 0x2D = 45 on WM07)
#   +16   9 x 20-byte PROPERTY records (the generic property bag):
#              [salt u32][nameHashLo u32][nameHashHi u32][typeTag u32][value u32]
#         `salt` is a per-asset constant repeated on every record (it is the
#         alignment oracle that proved the record size). 9 records => 180 bytes,
#         so the image-descriptor array begins at a FIXED offset 16+180 = 196.
#   +196  IMAGE-DESCRIPTOR ARRAY: one 30-byte record per stored sub-image
#         (a material packs several: diffuse + normal + specular, sometimes 4):
#              +0  u32  flags (1 on image[0], 0 after)
#              +4  u32  authoredWidth  * 256   (low byte = flags; use >>8)
#              +8  u32  authoredHeight * 256   (   "    "    "   ; use >>8)
#              +13 u8   FORMAT ENUM   (5=DXT1 6=DXT3 7=DXT5 9=ATI2/BC5 0-4=linear)
#              +20 u32  256           (clamp constant)
#              +26 u8   authored mip count = log2(max(authoredW,authoredH))+1
#         The array ends when +13 is not a valid enum or +26 not in 1..13; what
#         follows is a length-prefixed source path "/data/.../<name>.bmp".
#
# VERIFIED: image count matches reality (sky=1, walls/props=3 diffuse+normal+spec,
# sculptures=4); authored dims match the GPU (FemaleSkinBody 512x1024 authored ->
# 256x512 stored after 1 mip-drop = the byte-exact GPU copy). Format & name are
# 100% exact. See WATCHMEN_EXTRACTION_MASTER.md §6.
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
                    # slot 7 is the record the stride walk reaches through
                    # a 4-byte "drift" (four absent-slot bytes): the specSize map
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


def parse_texture_header(hdr, order="<"):
    """Deterministically parse a Texture .header blob.

    Returns dict(typename, path, name, images=[{enum,fmt,kind,aw,ah,mip,rec_off}])
    or None if `hdr` is not a Texture header.  order '<' PC / '>' X360+PS3 (the
    console record packs the same fields at shifted offsets: dims u32be@+6/+10,
    enum byte @+16, mips u32be@+26; console enums reflect platform re-encodes,
    e.g. X360 stores L8 spec-size maps as DXT1). `path`/`name` come straight from the
    embedded source path (100% correct naming); each image's `enum`/`fmt` are the
    engine's authoritative format; `aw`/`ah` are authored dims, `mip` the authored
    mip count.  (Stored byte-resolution still comes from the stream length — this
    block stores reduced-LOD data; see MASTER §6.)
    """
    if not is_texture_header(hdr, order):
        return None
    tlen = struct.unpack_from(order + "I", hdr, 0)[0]
    p = 4 + tlen + 4  # skip typeName + classId(0x2D)
    if p + 36 > len(hdr):
        return None
    p, prs = kapow_block.prop_walk(hdr, order)
    rs = 30  # image records are 30 bytes on BOTH engines
    # (only the PROPERTY records differ: 16 vs 20)
    images = []
    rec = p
    while rec + 30 <= len(hdr):
        v = _valid_rec(hdr, rec, order=order)
        if v is None:
            break
        fmt, kind = TEX_FMT[v["enum"]]
        images.append(
            {
                "enum": v["enum"],
                "fmt": fmt,
                "kind": kind,
                "aw": v["aw"],
                "ah": v["ah"],
                "mip": v["mip"],
                "rec_off": rec,
            }
        )
        rec += rs
    # source path: first length-prefixed "/data"|"/art" run after the records
    path = ""
    for marker in (b"/data", b"/Data", b"/art", b"/Art"):
        j = hdr.find(marker, rec - 4 if rec > 4 else 0)
        if j >= 4:
            plen = struct.unpack_from(order + "I", hdr, j - 4)[0]
            if 0 < plen < 512 and j + plen <= len(hdr):
                path = hdr[j : j + plen].decode("ascii", "replace").rstrip("\x00")
                break
    name = path.replace("\\", "/").rstrip("/").split("/")[-1].rsplit(".", 1)[0] if path else ""
    return {"typename": "Texture", "recsize": rs, "path": path, "name": name, "images": images}


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

    Without a slot (the stride walk and the drift rescue, which see formats
    only) the format rule applies: idx0 => diffuse; normal by format; a
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
# DETERMINISTIC texture layer planner.  Given a Texture
# header and the byte-exact bound stream length, return the exact layer
# layout that tiles the stream: a single multi-layer set, a 6-face cubemap, or
# an N-frame animation/array.  Resolves 1190/1190 level-block textures.
#
# Why this is needed: the header is a SEQUENTIAL serialized stream (texture.cpp
# FUN_005382aa reads field-by-field via typed-read vtables), so a fixed 30-byte
# descriptor stride slips on trailing layers. We read what we can at stride 30
# (+4-gap fallback), then use the exact stream length as an oracle to (a) detect
# cube (6x) / animation (Nx) multiples and (b) recover a dropped trailing layer
# by scanning the header for the missing descriptor record.
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


def _tex_path_off(hdr):
    for m in (b"/data", b"/Data", b"/art", b"/Art", b"/levels", b"/Levels"):
        j = hdr.find(m)
        if j >= 4:
            return j - 4
    return len(hdr)


def _valid_rec(hdr, r, powtwo=False, order="<"):
    if r + 30 > len(hdr):
        return None
    if order == ">":
        en = hdr[r + 16]
        mip = struct.unpack_from(">I", hdr, r + 26)[0]
        f4, f8 = struct.unpack_from(">II", hdr, r + 6)
    else:
        en = hdr[r + 13]
        mip = hdr[r + 26]
        f4, f8 = struct.unpack_from("<II", hdr, r + 4)
    if en not in TEX_ENUMS or not (1 <= mip <= 13):
        return None
    aw, ah = f4 >> 8, f8 >> 8
    if not (0 < aw <= 8192 and 0 < ah <= 8192):
        return None
    if powtwo and not ((aw & (aw - 1)) == 0 and (ah & (ah - 1)) == 0):
        return None
    return {"enum": en, "mip": mip, "aw": aw, "ah": ah}


def _stride_layers(hdr, order="<"):
    info = parse_texture_header(hdr, order)
    if not info or not info["images"]:
        return [], 0, 0, 30
    rs = info.get("recsize", 30)
    r0 = info["images"][0]["rec_off"]
    end = _tex_path_off(hdr)
    out = []
    r = r0
    last = r0
    while r + 27 <= end:
        v = _valid_rec(hdr, r, order=order)
        if v:
            v["drift"] = False
            out.append(v)
            last = r
            r += rs
            continue
        v = _valid_rec(hdr, r + 4, order=order)  # 4-byte gap = the specSize slot marker
        if v:
            v["drift"] = True
            out.append(v)
            last = r + 4
            r += rs + 4
            continue
        break
    return out, last, end, rs


def plan_texture_layers(hdr, stream_len):
    """Return dict(kind, layers, count) where kind in
    {'single','cube','anim','fail'} and Sum(layer chains) * count == stream_len.
      single: one material, layers = [diffuse, normal, spec, ...]
      cube  : count == 6, layers describe ONE face
      anim  : count == N frames, layers describe ONE frame (a full material set)
    """
    ex = _exact_texture_plan(hdr, stream_len)
    if ex:
        return ex
    L, last, end, rs = _stride_layers(hdr)
    if not L:
        return {"kind": "fail", "layers": [], "count": 0}

    def total(layers):
        return sum(chain_bytes(x["enum"], x["aw"], x["ah"], x["mip"]) for x in layers)

    S = total(L)
    if S <= 0:
        return {"kind": "fail", "layers": L, "count": 0}
    if abs(S - stream_len) <= 64:
        return {"kind": "single", "layers": L, "count": 1}
    if abs(S * 6 - stream_len) <= 400:
        return {"kind": "cube", "layers": L, "count": 6}
    # EXACT frame-multiple animation first (validated on the Part 2 level
    # blocks); inexact multiples wait until after the dropped-layer recovery --
    # Part 1 drift can make a loose multiple "fit" a stream that is really
    # layers (Caustics01_002: 60*184 ~ 11120 which is truly 16x16 + 128x128).
    n = round(stream_len / S)
    if 2 <= n <= 64 and S * n == stream_len:
        return {"kind": "anim", "layers": L, "count": n}
    # recover a dropped trailing layer using the stream length as the oracle
    if S < stream_len - 64:
        pos = last + rs
        acc = []
        add = 0
        need = stream_len - S
        while pos + 30 <= end and add < need - 64:
            v = _valid_rec(hdr, pos, powtwo=True)
            if v:
                c = chain_bytes(v["enum"], v["aw"], v["ah"], v["mip"])
                if add + c <= need + 64:
                    acc.append(v)
                    add += c
                    pos += rs
                    continue
            pos += 1
        if acc and abs(S + add - stream_len) <= 64:
            return {"kind": "single", "layers": L + acc, "count": 1}
        if acc:
            # repaired set as an EXACT frame multiple (Caustics01_001: 32 x
            # [16x16 + drifted 128x128] = 355840)
            S2 = S + add
            n2 = round(stream_len / S2) if S2 else 0
            if 2 <= n2 <= 64 and n2 * S2 == stream_len:
                return {"kind": "anim", "layers": L + acc, "count": n2}
    if 2 <= n <= 64 and abs(S * n - stream_len) <= max(256, n * 8):
        return {"kind": "anim", "layers": L, "count": n}  # each frame = full set L (loose)
    en0 = L[0]
    S1 = chain_bytes(en0["enum"], en0["aw"], en0["ah"], en0["mip"])
    n1 = round(stream_len / S1)
    if 2 <= n1 <= 64 and S1 >= 256 and abs(S1 * n1 - stream_len) <= max(256, n1 * 8):
        return {"kind": "anim", "layers": [en0], "count": n1}
    return {"kind": "fail", "layers": L, "count": 0}


def header_dims(header):
    """Candidate (width, height) pairs of a texture header without a parseable
    plan: every power of two 32..4096 stored as a little-endian u32 at any byte
    offset (a bytes search for each of the eight values), largest first,
    squares then pairs within a factor 2."""
    pows = {v for v in (32 << k for k in range(8)) if struct.pack("<I", v) in header}
    pows = sorted(pows, reverse=True)
    dims = [(a, a) for a in pows]
    for a in pows:
        for b in pows:
            if a != b and a // 2 <= b <= a * 2:
                dims.append((a, b))
    seen, out = set(), []
    for d in dims:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out or [(512, 512), (256, 256), (1024, 1024)]
