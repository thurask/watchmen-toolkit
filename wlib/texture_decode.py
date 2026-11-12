"""Texture pixels: the DDS container (`make_dds`, `mip_chain_size`), the block
decoders (`decode_dxt_base`, `decode_bc5_base`, `ati2_xy`, `normal_to_png`),
one stored layer to an image (`decode_one_layer`), and the console layouts:
Xbox 360 tiling and 16-bit byte swap (`xg2d_offset`, `bswap16`,
`x360_layer_bytes`, `x360_base_level`) and the PS3 per-layer segments and
swizzle (`ps3_segments`, `rsx_unswizzle`, `ps3_layer_image`); the top mip of
one layer named by its descriptor on any platform (`layer_image`).
"""

import io
import os
import struct
import sys

import numpy as np
from PIL import Image

# the flat wlib modules import each other by name (`import kapow_props`); one path
# setup for this module, also when it is run as a script or loaded by file path.
# Append, never insert(0): flat module names must not shadow the stdlib.
_WLIB = os.path.dirname(os.path.abspath(__file__))
if _WLIB not in sys.path:
    sys.path.append(_WLIB)
import texture_header  # noqa: E402


DDS_MAGIC = 0x20534444
FOURCC = {"DXT1": b"DXT1", "DXT3": b"DXT3", "DXT5": b"DXT5", "BC5": b"ATI2"}


def mip_chain_size(w, h, bb):
    total = mips = 0
    while True:
        total += max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * bb
        mips += 1
        if w == 1 and h == 1:
            break
        w = max(1, w >> 1)
        h = max(1, h >> 1)
    return total, mips


def base_mip_bytes(w, h, bb):
    return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * bb


def make_dds(w, h, mips, fmt):
    flags = 0x1007 | ((0x20000 | 0x80000) if mips > 1 else 0)
    bb = 8 if fmt == "DXT1" else 16
    caps1 = 0x1000 | ((0x400000 | 0x8) if mips > 1 else 0)
    pf = struct.pack("<8I", 32, 4, struct.unpack("<I", FOURCC[fmt])[0], 0, 0, 0, 0, 0)
    hdr = (
        struct.pack("<7I", 124, flags, h, w, base_mip_bytes(w, h, bb), 0, max(1, mips))
        + b"\x00" * 44
        + pf
    )
    hdr += struct.pack("<5I", caps1, 0, 0, 0, 0)
    return struct.pack("<I", DDS_MAGIC) + hdr


def decode_dxt_base(data, w, h, fmt):
    """Top mip of a DXT1 / DXT3 / DXT5 layer -> (h, w, 4) uint8 RGBA (Pillow's DDS
    decoder; DXT3 = explicit 4-bit alpha, DXT5 = interpolated alpha), or None."""
    bb = 8 if fmt == "DXT1" else 16
    base = base_mip_bytes(w, h, bb)
    if w % 4 or h % 4 or len(data) < base:
        return None
    try:
        im = Image.open(io.BytesIO(make_dds(w, h, 1, fmt) + data[:base]))
        im.load()
        return np.array(im.convert("RGBA"))
    except (OSError, ValueError, EOFError):  # Pillow refuses the data
        return None


def _bc4_channel(blocks8, w, h):
    n = blocks8.shape[0]
    e0 = blocks8[:, 0].astype(np.int32)
    e1 = blocks8[:, 1].astype(np.int32)
    pal = np.zeros((n, 8), np.float32)
    pal[:, 0] = e0
    pal[:, 1] = e1
    gt = e0 > e1
    # the interpolated entries are rounded to the nearest integer, as the D3D
    # reference decoder does (an integer / 7 or / 5 is never exactly x.5, so the
    # rounding rule for ties does not matter); truncation would give -1 LSB
    for i in range(1, 7):
        pal[:, i + 1] = np.where(gt, np.rint(((7 - i) * e0 + i * e1) / 7.0), pal[:, i + 1])
    for i in range(1, 5):
        pal[:, i + 1] = np.where(~gt, np.rint(((5 - i) * e0 + i * e1) / 5.0), pal[:, i + 1])
    pal[:, 6] = np.where(~gt, 0.0, pal[:, 6])
    pal[:, 7] = np.where(~gt, 255.0, pal[:, 7])
    bits = np.zeros(n, np.uint64)
    for k in range(6):
        bits |= blocks8[:, 2 + k].astype(np.uint64) << np.uint64(8 * k)
    idx = np.zeros((n, 16), np.intp)
    for j in range(16):
        idx[:, j] = ((bits >> np.uint64(3 * j)) & np.uint64(7)).astype(np.intp)
    vals = np.take_along_axis(pal, idx, axis=1)
    bw, bh = w // 4, h // 4
    return np.clip(vals.reshape(bh, bw, 4, 4).transpose(0, 2, 1, 3).reshape(h, w), 0, 255).astype(
        np.uint8
    )


def decode_bc5_base(data, w, h):
    base = base_mip_bytes(w, h, 16)
    if len(data) < base or w % 4 or h % 4:
        return None
    blk = np.frombuffer(data[:base], np.uint8).reshape(-1, 16)
    return _bc4_channel(blk[:, 0:8], w, h), _bc4_channel(blk[:, 8:16], w, h)


def ati2_xy(blocks):
    """(first, second) 8-byte-block channels of a PC `ATI2` layer -> (X, Y).

    Direct3D 9's ATI2 keeps the Y (green) block first and the X (red) block
    second; the game's pixel shaders multiply sampler .x with the tangent and .y
    with the bitangent (DeferredMain2PS: `mad r1.xyz, r0.x, v4, r1`).  Measured on
    the extracted maps: with the blocks in file order the mixed partials do not
    match (d(first)/dv vs d(second)/du correlate 0.17), swapped they do (0.57);
    the X360 (enum 10) and PS3 (DXT5) copies of the same maps already come out
    X-first (0.78).  Y points along +v (the stored bitangent is +dP/dv).
    Rechecked with the rounding BC4 decoder on the first 12 Part 2 maps of
    at least 128 px per platform: correlation of d(X)/dv with d(Y)/du 0.36 with the
    PC blocks swapped against 0.08 in file order, and 0.36 in file order against
    0.08 swapped on Xbox 360 (measured; mean over the maps)."""
    return blocks[1], blocks[0]


def normal_to_png(X, Y, path):
    Xf = X.astype(np.float32) / 255 * 2 - 1
    Yf = Y.astype(np.float32) / 255 * 2 - 1
    Z = np.sqrt(np.clip(1 - Xf * Xf - Yf * Yf, 0, 1))
    B = ((Z * 0.5 + 0.5) * 255).clip(0, 255).astype(np.uint8)
    Image.fromarray(np.stack([X, Y, B], -1)).save(path)


def image_coherence(a):
    if a is None:
        return 1e9
    g = a.astype(np.int32).mean(2) if a.ndim == 3 else a.astype(np.int32)
    return float((np.abs(np.diff(g, axis=1)).mean() + np.abs(np.diff(g, axis=0)).mean()) / 2)


def looks_like_normal(XY):
    if XY is None:
        return False
    X, Y = XY
    if not (112 <= X.mean() <= 144 and 112 <= Y.mean() <= 144):
        return False
    return image_coherence(X) < 16 and image_coherence(Y) < 16


def unpad_linear(buf, en, w, h):
    """Top mip of a LINEAR layer without the 4-byte row padding (no-op unless the
    row size is not a multiple of 4, i.e. L8 narrower than 4 texels)."""
    k, unit = texture_header.TEX_FMT[en][1]
    row = w * unit
    if k == "blk" or row % 4 == 0:
        return buf
    pitch = (row + 3) & ~3
    return b"".join(buf[y * pitch : y * pitch + row] for y in range(h))


def decode_one_layer(buf, en, w, h, normal=False):
    """Decode a single layer's TOP mip to an RGB array (or grayscale for L8).
    normal=True: layer is a normal map -- reconstruct a proper tangent-space
    RGB normal. For PS3's DXT5-packed normals the vector is stored X->alpha,
    Y->green (the classic DXT5nm layout; R/B are constant filler), so we rebuild
    (X, Y, Z=sqrt(1-X^2-Y^2)); ATI2/BC5 already carries X,Y in two channels."""
    name = texture_header.TEX_FMT[en][0]
    match name:
        case "DXT5" | "DXT3" if normal:
            rgba = decode_dxt_base(buf, w, h, name)
            if rgba is None:
                return None
            X = rgba[:, :, 3].astype(np.float32)
            Y = rgba[:, :, 1].astype(np.float32)  # A, G
            Xf = X / 255 * 2 - 1
            Yf = Y / 255 * 2 - 1
            Z = (np.sqrt(np.clip(1 - Xf * Xf - Yf * Yf, 0, 1)) * 0.5 + 0.5) * 255
            return np.stack(
                [X.astype(np.uint8), Y.astype(np.uint8), Z.clip(0, 255).astype(np.uint8)], -1
            )
        case "DXT1" | "DXT3" | "DXT5":
            return decode_dxt_base(buf, w, h, name)
        case "ATI2":  # BC5 normal map
            xy = decode_bc5_base(buf, w, h)
            if not xy:
                return None
            if en == 9:  # PC ATI2 stores the Y block first (see ati2_xy)
                xy = ati2_xy(xy)
            Xf = xy[0].astype(np.float32) / 255 * 2 - 1
            Yf = xy[1].astype(np.float32) / 255 * 2 - 1
            Z = (np.sqrt(np.clip(1 - Xf * Xf - Yf * Yf, 0, 1)) * 0.5 + 0.5) * 255
            return np.stack([xy[0], xy[1], Z.clip(0, 255).astype(np.uint8)], -1)
        case "X8R8G8B8" | "A8R8G8B8":
            need = w * h * 4
            if len(buf) < need:
                return None
            a = np.frombuffer(buf[:need], np.uint8).reshape(h, w, 4)
            return (
                a[:, :, 2::-1].copy() if name == "X8R8G8B8" else a[:, :, [2, 1, 0, 3]].copy()
            )  # X8->RGB, A8->RGBA
        case "L8":
            need = w * h
            if len(buf) < need:
                return None
            return np.frombuffer(buf[:need], np.uint8).reshape(h, w)
        case "DXT3A":
            return _decode_dxt3a(buf, w, h)
    return None


def _decode_dxt3a(buf, w, h):
    """X360 DXT3A (the explicit-alpha half of a DXT3 block on its own): 8 bytes per
    4x4 block, one 4-bit value per texel, low nibble first, rows top to bottom.
    Returns a grayscale array like L8 (value * 17), or None."""
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    if len(buf) < bw * bh * 8:
        return None
    b = np.frombuffer(buf[: bw * bh * 8], np.uint8).reshape(bh, bw, 4, 2)
    t = np.stack([b[..., 0] & 15, b[..., 0] >> 4, b[..., 1] & 15, b[..., 1] >> 4], -1)
    img = t.reshape(bh, bw, 4, 4).transpose(0, 2, 1, 3).reshape(bh * 4, bw * 4)
    return (img[:h, :w] * 17).astype(np.uint8)


# ---------------------------------------------------------------------------
# Console texture streams.
#   PS3 : per-layer [36-byte header][data]; data size = u32be @ hdr+8 (self-
#         describing; a layer may carry MORE mips than the PC plan, e.g. ATI2
#         stored with the full chain). Pixel data is byte-identical to PC.
#   X360: layers concatenated raw; every mip is TILED (XGAddress2DTiledOffset)
#         and the whole stream is 16-bit byte-swapped (GPU 8-in-16). Per-layer
#         size rule (validated on bordello, 230/272 exact vs PC plans + the
#         L8->DXT1 re-encode visible in the console header records): mips are
#         stored individually while min(w,h) >= 32 texels, each padded to
#         32x32 BLOCKS; all smaller mips share one packed 32x32-block tail.
# ---------------------------------------------------------------------------
def bswap16(b):
    import array as _arr

    a = _arr.array("H")
    a.frombytes(b[: len(b) & ~1])
    a.byteswap()
    return a.tobytes() + b[len(b) & ~1 :]


def xg2d_offset(x, y, w, tp):
    """XGAddress2DTiledOffset (Xenos): element offset of (x,y) in a tiled
    surface of width w elements, tp = bytes per element."""
    alw = (w + 31) & ~31
    lb = (tp >> 2) + ((tp >> 1) >> (tp >> 2))
    macro = ((x >> 5) + (y >> 5) * (alw >> 5)) << (lb + 7)
    micro = ((x & 7) + ((y & 6) << 2)) << lb
    off = macro + ((micro & ~15) << 1) + (micro & 15) + ((y & 8) << (3 + lb)) + ((y & 1) << 4)
    return (
        ((off & ~511) << 3)
        + ((off & 448) << 2)
        + (off & 63)
        + ((y & 16) << 7)
        + (((((y & 8) >> 2) + (x >> 3)) & 3) << 6)
    ) >> lb


def _xg_untile(data, we, he, bpe, alw=None, yoff=0):
    """Linearize a tiled X360 surface: we x he elements of bpe bytes
    (alw = aligned surface width used for tiling, min 32).
    yoff shifts the source row read up by yoff element-rows -- used for the
    D3D9 packed-mip-tail case where a very short surface stores its base level
    BELOW the packed tail (see _thin_mip_yoff)."""
    alw = max(alw or we, 32)
    if we <= 0 or he <= 0:
        return b""
    import numpy as np

    # every element at once: xg2d_offset is integer arithmetic that works on numpy arrays
    y, x = np.mgrid[0:he, 0:we].astype(np.int64)
    s = xg2d_offset(x.ravel(), y.ravel() + yoff, alw, bpe) * bpe
    src = np.frombuffer(data, np.uint8)
    out = np.zeros((we * he, bpe), np.uint8)
    ok = s + bpe <= len(src)  # elements past the end of the data stay 0
    out[ok] = src[s[ok, None] + np.arange(bpe)]
    return out.tobytes()


def _x360_packed_offset(kind, unit, w, h, we, he):
    """Where the BASE level of an X360 layer sits in its tile: (xo, yo, start).
    Levels whose pow2-padded TEXEL dims are both >= 32 are stored normally at
    (0,0). Smaller bases live in the shared packed tail; empirically (P1
    console audit, brute-forced vs PC ground truth on all 55
    affected sub-32px textures, incl. 8x64 A8R8G8B8 / 64x16 DXT1 / 16x16 DXT1 /
    4x4 ATI2 classes): the base packs 16 TEXELS in from the tile edge along its
    short axis — x for taller-or-square, y for wider — i.e. 16//blk elements.
    4x4-texel single-block layers sit at special spots: element (1,0) for
    8-byte blocks (DXT1), (26,0) for 16-byte blocks (ATI2/DXT5).
    A wide blk layer (we>=32 & he<=4) comes out at y 4.

    `start` is None, or the element at which a base stored as its own tiled
    surface (not at a place in the tile) begins. That is the case for the one
    packed DXT1 base with a side that is not a power of two (ArrowMore 16x24,
    both parts): its 24 blocks are byte-identical to PC's (after the 16-bit
    swap) as a 4x6-block tiled surface starting at element 28, while at
    (4,0) of the tile only half of its columns lie (measured; no other
    shipped texture to generalise from)."""
    pw = 1 << max(0, (max(w, 1) - 1).bit_length())
    ph = 1 << max(0, (max(h, 1) - 1).bit_length())
    if min(pw, ph) >= 32:
        return 0, 0, None
    blk = 4 if kind == "blk" else 1
    if kind == "blk" and we <= 1 and he <= 1:
        return (1 if unit == 8 else 26), 0, None
    if kind == "blk" and unit == 8 and (w, h) == (16, 24):
        return 0, 0, 28
    if unit == 16 and kind == "blk" and we >= 32 and he <= 4:
        # full-tile-wide thin rows of 128-bit blocks sit at y=16 ELEMENTS
        # (HoneyPot_lightChain's ATI2 normal: exact vs PC)
        return 0, 16, None
    if pw > ph:
        return 0, 16 // blk, None
    return 16 // blk, 0, None


def _thin_mip_yoff(kind, we, he):
    """Row offset of the base mip inside a tiled X360 surface.
    Normally 0.  For a wide, VERY short block-compressed surface (spans >=1 full
    32-block macro-tile wide but <=4 blocks tall) the D3D9 packed mip tail is
    stored in the top rows and the base level sits BELOW it -- verified 0.00 vs
    PC on the only two such textures shipped (FloorCable_BlackPlastic 64x4 blk,
    HoneyPot_lightChain 32x1 blk), both offset by 4 rows.  Gated tightly so it
    can NEVER touch a normal texture (none other match we>=32 & he<=4)."""
    return 4 if (kind == "blk" and we >= 32 and he <= 4) else 0


def x360_layer_bytes(en, w, h, mips):
    """Stored byte size of one X360 texture layer (see rule above). The packed
    tail is the current mip's block dims each aligned UP to 32 blocks (not a
    fixed 32x32) -- correct for wide/thin textures like 256x16 (64x4 blocks ->
    64x32 tail = 16384; a fixed 8192 would mis-plan them as 2x anim).
    For square small mips (<=32 blocks) this is 32x32."""
    _, (kind, unit) = texture_header.TEX_FMT[en]
    blk = 4 if kind == "blk" else 1
    total = 0
    lvl = 0
    tail = False
    while lvl < mips:
        if min(w, h) >= 32:
            wb = (max(1, (w + blk - 1) // blk) + 31) & ~31
            hb = (max(1, (h + blk - 1) // blk) + 31) & ~31
            total += wb * hb * unit
        else:
            tail = True
            break
        w = max(1, w >> 1)
        h = max(1, h >> 1)
        lvl += 1
    if tail or lvl < mips:
        wb = (max(1, (w + blk - 1) // blk) + 31) & ~31
        hb = (max(1, (h + blk - 1) // blk) + 31) & ~31
        total += wb * hb * unit
    return total


def ps3_segments(stream):
    """Walk PS3 per-layer [36B header][data] segments; returns [(data_off, size)]
    or None if the stream doesn't parse as a PS3 texture stream."""
    segs = []
    p = 0
    while p + 36 <= len(stream):
        sz = struct.unpack_from(">I", stream, p + 8)[0]
        if not (16 <= sz <= len(stream) - p - 36):
            return segs if segs and p >= len(stream) - 64 else None
        segs.append((p + 36, sz))
        p += 36 + sz
    return segs if segs and p >= len(stream) - 64 else None


def console_recover_layers(header, stream, L, last, end, rs):
    """Recover trailing texture layers the stride walk dropped (serializer
    drift), using the stream as the size oracle -- the console analogue of the
    PC dropped-layer recovery in plan_texture_layers. PS3: match each self-
    describing segment's full-chain byte size to a byte-scanned power-of-two
    record. X360: byte-scan records and accept only while the platform-padded
    sizes still tile the stream exactly. Returns the fuller layer list (>= L)."""
    segs = ps3_segments(stream)
    # candidate records anywhere in the record area (byte-granular scan)
    cands = []
    pos = last + rs
    while pos + 30 <= end:
        v = texture_header._valid_rec(header, pos, powtwo=True, order=">")
        if v:
            cands.append(v)
            pos += rs
        else:
            pos += 1
    if not cands:
        return L
    if segs is not None:  # ---- PS3: segments are exact
        if len(segs) <= len(L):
            return L
        out = list(L)
        ci = 0
        for si in range(len(L), len(segs)):
            want = segs[si][1]
            pick = None
            for k in range(ci, len(cands)):
                v = cands[k]
                if (
                    abs(texture_header.chain_bytes(v["enum"], v["aw"], v["ah"], v["mip"]) - want)
                    <= 64
                ):
                    pick = v
                    ci = k + 1
                    break
            if pick is None:
                break
            out.append(pick)
        return out
    # ---- X360: accept recovered records only if total padded size == stream
    base = sum(x360_layer_bytes(x["enum"], x["aw"], x["ah"], x["mip"]) for x in L)
    add = []
    acc = 0
    for v in cands:
        c = x360_layer_bytes(v["enum"], v["aw"], v["ah"], v["mip"])
        if base + acc + c <= len(stream) + 64:
            add.append(v)
            acc += c
        if base + acc == len(stream):
            return L + add
    return L  # no exact fill -> stay conservative


def rsx_unswizzle(buf, w, h, unit=1):
    """PS3/RSX Morton (Z-order) unswizzle for UNCOMPRESSED layers (L8 etc.).
    DXT layers are stored linearly on RSX; L8 is swizzled — verified byte-exact
    vs the PC linear L8 across all Part-2 specSize maps.  For
    non-square pow2 textures the remaining high bits of the larger dimension
    ride linearly above the interleaved low bits (standard RSX layout).
    Returns the linear top mip (w*h*unit bytes); extra chain bytes ignored."""
    import numpy as np

    if w & (w - 1) or h & (h - 1) or w * h * unit > len(buf):
        return buf  # not unswizzlable -> leave as-is
    n = w * h
    idx = np.arange(n, dtype=np.uint64)
    xs = np.zeros(n, dtype=np.uint64)
    ys = np.zeros(n, dtype=np.uint64)
    bx = by = 0
    lw = w.bit_length() - 1
    lh = h.bit_length() - 1
    src = idx
    for b in range(lw + lh):
        if bx < lw and by < lh:  # interleave: x bit first (LSB)
            if (b & 1) == 0:
                xs |= ((src >> np.uint64(b)) & np.uint64(1)) << np.uint64(bx)
                bx += 1
            else:
                ys |= ((src >> np.uint64(b)) & np.uint64(1)) << np.uint64(by)
                by += 1
        elif bx < lw:  # leftover bits -> wider dim, linear
            xs |= ((src >> np.uint64(b)) & np.uint64(1)) << np.uint64(bx)
            bx += 1
        else:
            ys |= ((src >> np.uint64(b)) & np.uint64(1)) << np.uint64(by)
            by += 1
    a = np.frombuffer(buf[: n * unit], dtype=np.uint8)
    if unit == 1:
        out = np.empty(n, dtype=np.uint8)
        out[(ys * np.uint64(w) + xs).astype(np.int64)] = a
    else:
        a = a.reshape(n, unit)
        out = np.empty((n, unit), dtype=np.uint8)
        out[(ys * np.uint64(w) + xs).astype(np.int64)] = a
    return out.tobytes()


def _texel32_to_pc(data, src):
    """Reorder console 32bpp (A8R8G8B8/X8R8G8B8) texel bytes to the PC little-
    endian D3D layout (B,G,R,A) the shared decoder expects (P1 console audit:
    6 lightprojector/lensflare maps per console).
      src='ps3'  : RSX stores big-endian A,R,G,B      -> reverse each texel.
      src='x360' : stream holds PLAIN BE A,R,G,B (NOT GPU 8-in-16 swapped);
                   the unconditional bswap16 turns it into R,A,B,G -> [2,3,0,1].
    """
    import numpy as np

    n = len(data) & ~3
    a = np.frombuffer(data[:n], np.uint8).reshape(-1, 4)
    perm = [3, 2, 1, 0] if src == "ps3" else [2, 3, 0, 1]
    return a[:, perm].tobytes() + data[n:]


def x360_level0_bytes(en, w, h):
    """Stored bytes of level 0 of an X360 layer: its block grid padded to 32 x 32
    elements (also the step from one cube face to the next inside a level)."""
    _, (kind, unit) = texture_header.TEX_FMT[en]
    blk = 4 if kind == "blk" else 1
    we = max(1, (w + blk - 1) // blk)
    he = max(1, (h + blk - 1) // blk)
    return ((we + 31) & ~31) * ((he + 31) & ~31) * unit


def x360_base_level(raw, en, w, h):
    """Top mip of one X360 layer (or cube face) as an image array, or None.  `raw`
    starts at the layer's level 0: 16-bit swap, untile, crop out of the packed
    tail when the layer is smaller than 32 texels."""
    _, (kind, unit) = texture_header.TEX_FMT[en]
    blk = 4 if kind == "blk" else 1
    we = max(1, (w + blk - 1) // blk)
    he = max(1, (h + blk - 1) // blk)
    # width aligned UP to 32 like every consumer (xg2d_offset/_x360_layer_bytes);
    # max(we,32) would under-size the tile buffer for non-pow2 widths > 32
    # blocks and zero-fill the tail of the untiled layer.
    need = ((we + 31) & ~31) * ((he + 31) & ~31) * unit
    buf = bswap16(raw[:need])
    xo, yo, start = _x360_packed_offset(kind, unit, w, h, we, he)
    if start is not None:
        lin = _xg_untile(buf[start * unit :], we, he, unit, alw=32)
    elif (xo or yo) and (max(we + xo, 32) * max(he + yo, 32) * unit) <= len(buf):
        import numpy as _np  # packed-tail base: untile the

        tw = max(we + xo, 32)
        th = max(he + yo, 32)  # full tile, crop at (xo,yo)
        full = _xg_untile(buf, tw, th, unit, alw=tw)
        t = _np.frombuffer(full, _np.uint8).reshape(th, tw, unit)
        lin = t[yo : yo + he, xo : xo + we].reshape(-1, unit).tobytes()
    else:
        lin = _xg_untile(buf, we, he, unit, alw=we, yoff=_thin_mip_yoff(kind, we, he))
    if kind == "lin" and unit == 4:  # 32bpp: undo bswap16-scramble -> PC BGRA
        lin = _texel32_to_pc(lin, "x360")
    return decode_one_layer(lin, en, w, h)


def ps3_layer_image(data, lay, normal):
    """One PS3 layer (or cube face) -> image array.  DXT data is linear;
    uncompressed layers are RSX-swizzled, 32-bit ones big-endian ARGB."""
    kind, unit = texture_header.TEX_FMT[lay["enum"]][1]
    if kind != "blk":  # uncompressed (L8...) -> RSX swizzled
        data = rsx_unswizzle(data, lay["aw"], lay["ah"], unit)
        if unit == 4:  # 32bpp: BE ARGB -> PC BGRA
            data = _texel32_to_pc(data, "ps3")
    return decode_one_layer(data, lay["enum"], lay["aw"], lay["ah"], normal=normal)


def layer_image(desc, data, order):
    """Top mip of the one layer of a texture descriptor (texture_header.
    read_descriptor) as an image array, or None for a format enum without a
    decoder, a type other than 2D, or data the decoder cannot use.  `data`
    starts at the layer: PC (order '<') the mip chain, linear rows padded to 4
    bytes; Xbox 360 (big-endian, descriptor `size` set) the tiled, 16-bit
    swapped chain; PS3 (big-endian, `size` 0) the 36-byte RSX descriptor and
    the chain (texture_header.layer_bytes gives the stored length)."""
    en, w, h = desc["enum"], desc["width"], desc["height"]
    if en not in texture_header.TEX_FMT or desc["type"] != 1:
        return None
    if order == "<":
        return decode_one_layer(unpad_linear(data, en, w, h), en, w, h)
    if desc["size"]:
        return x360_base_level(data, en, w, h)
    return ps3_layer_image(data[36:], {"enum": en, "aw": w, "ah": h}, False)
