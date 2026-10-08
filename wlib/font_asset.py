#!/usr/bin/env python3
"""`.font` assets (asset type `font`, 0x62f2722a): the baked bitmap font.

Layout, read from the engine's loader (`Font` header reader 0x540c6e, which calls the
`FontBuffer` reader 0x44245e; the texture descriptor is the one every texture layer
uses, 0x429e77).  All integers and floats are little-endian on PC and big-endian on
Xbox 360 / PS3:

    u8      has_data          0 = no font buffer follows (0x540c75)
    -- texture descriptor, 29 bytes (0x429e77) --
    u32     width, height
    u32     enum              texture format id (watchmen_extract.TEX_FMT; 1 = A8R8G8B8)
    u32     usage             texture usage (0x456d46); 0 in all 18 files; JSON keys usage
                              and x
    u32     type              1 = 2D
    u8      alpha
    u32     mips
    u32     size              0 on PC and PS3; on Xbox 360 the stored byte size of the atlas
    -- atlas pixels, inline (the font has no stream file) --
    PC      the full mip chain, rows padded to 4 bytes (the locked D3D pitch)
    X360    `size` bytes, tiled and 16-bit swapped like a texture stream layer
    PS3     a 36-byte RSX descriptor (its u32 at +8 = byte count) and the mip chain
    -- FontBuffer fields (0x4424c7 .. 0x44253d) --
    u32     glyph_height      buffer +0x1c: the cell height in pixels
    u32     b04               buffer +0x04: flags; bit 2 = every glyph advances by f24
                              (0x43d390)
    u32     b38               buffer +0x38: horizontal alignment, overwritten at each
                              TextBox draw (0x43d26e)
    u32     b3c               buffer +0x3c: vertical alignment, never read
    f32 x2  v28               buffer +0x28: (letter spacing, extra line spacing); [0] is
                              overwritten at each draw
    f32 x2  v30               buffer +0x30: (scale x, scale y); overwritten at each draw
    f32     glyph_height_v    buffer +0x20 = (glyph_height - 1) / atlas height (0x4426b9)
    f32     f24               buffer +0x24: the advance of every glyph when b04 & 4; the
                              debug-font builder stores the mean glyph width there
                              (0x4428d5); 0 in the game's fonts
    u32     glyph_count
    -- glyph record, 27 bytes (0x442566 .. 0x4425c0); 0x20 bytes in memory --
    u16     code              character code (the lookup key, 0x441f47)
    f32 x2  offset            +0x04; pixels from the pen position to the quad's top-left
                              (0x43efbb)
    f32     width             +0x0c; the advance in pixels (0x43d390; the builder averages
                              this field into +0x24)
    f32 x2  uv                +0x10; top-left corner in atlas units (inferred, checked:
                              u * atlas width is a whole pixel in every glyph)
    f32     u_width           +0x18; = width / atlas width in every glyph (checked)
    u8      flag              +0x1c; 1 = icon glyph: drawn white with the current alpha,
                              not with the text colour (0x43efbb)

A character code without a glyph is drawn as '@' (code 64, 0x43ef1f): `fallback_code`.

The JSON names the FontBuffer fields `flags`, `h_align`, `v_align`, `spacing`, `scale`
and `fixed_advance`; the offset-style keys `b04`, `b38`, `b3c`, `v28`, `v30` and `f24`
hold the same values and remain as aliases (`build` takes the name when the dict has it).

`parse` keeps every byte: `build(doc, pixels)` returns the file again.  The pixel block
is not put into the JSON; `atlas_image` decodes its top mip to RGBA.
"""

import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)

FORMAT = "kapow-font/1"
_DESC = "5IBII"  # width height enum x type alpha mips size
_DESC_LEN = 29
_GLYPH_LEN = 27

#: what in the JSON is a reading of the values and not of the loader code
INFERRED = {
    "glyphs[].uv": "top-left corner in atlas units; inferred, u*width is a whole pixel",
    "glyphs[].rect_px": "derived: uv * atlas size, width, glyph_height",
}
NOT_ESTABLISHED = []
#: (name, offset-style alias) of the FontBuffer fields
ALIASES = (
    ("flags", "b04"),
    ("h_align", "b38"),
    ("v_align", "b3c"),
    ("spacing", "v28"),
    ("scale", "v30"),
    ("fixed_advance", "f24"),
)


def _named(d, name, alias):
    """d[name] when the dict has it, else d[alias] (a JSON written before the names)."""
    return d[name] if name in d else d[alias]


#: the character drawn for a code that has no glyph: '@' (0x43ef1f)
FALLBACK_CODE = 64


def _read_bytes(path):
    """The file's bytes; the handle is closed before returning."""
    with open(path, "rb") as fh:
        return fh.read()


class FontError(ValueError):
    pass


def detect_order(data):
    """'<' or '>' from the texture descriptor (width and height are small powers of two)."""
    for bo in "<>":
        try:
            w, h, en, _x, typ, alpha, mips, _size = struct.unpack_from(bo + _DESC, data, 1)
        except struct.error:
            break
        if 0 < w <= 8192 and 0 < h <= 8192 and typ in (1, 2) and alpha <= 1 and 1 <= mips <= 14:
            return bo
    raise FontError("no texture descriptor at offset 1")


def _tex_fmt():
    import watchmen_extract as wx

    return wx


def _pixel_bytes(data, tex, bo):
    """(offset, length) of the inline atlas block that follows the descriptor."""
    p = 1 + _DESC_LEN
    if bo == "<":
        wx = _tex_fmt()
        if tex["enum"] not in wx.TEX_FMT:
            raise FontError("texture format id %d" % tex["enum"])
        return p, wx._chain_bytes_exact(tex["enum"], tex["width"], tex["height"], tex["mips"])
    if tex["size"]:  # Xbox 360: the descriptor carries the stored size
        return p, tex["size"]
    # PS3: 36-byte RSX descriptor, byte count at +8
    if p + 36 > len(data):
        raise FontError("truncated RSX descriptor")
    (n,) = struct.unpack_from(">I", data, p + 8)
    return p, 36 + n


def parse(data, order=None):
    """Font JSON dict (format kapow-font/1).  Raises FontError on a file that does not
    follow the loader's grammar to its last byte."""
    if not data:
        raise FontError("empty file")
    if data[0] == 0:
        if len(data) != 1:
            raise FontError("has_data = 0 but %d bytes follow" % (len(data) - 1))
        return {"format": FORMAT, "order": order or "<", "has_data": False, "glyphs": []}
    if data[0] != 1:
        raise FontError("has_data byte is %d" % data[0])
    bo = order or detect_order(data)
    try:
        w, h, en, x, typ, alpha, mips, size = struct.unpack_from(bo + _DESC, data, 1)
    except struct.error:
        raise FontError("truncated texture descriptor")
    tex = {
        "width": w,
        "height": h,
        "enum": en,
        "x": x,
        "usage": x,  # TextureBuffer +0x10 (0x456d46)
        "type": typ,
        "alpha": bool(alpha),
        "mips": mips,
        "size": size,
    }
    off, n = _pixel_bytes(data, tex, bo)
    p = off + n
    try:
        gh, b04, b38, b3c = struct.unpack_from(bo + "4I", data, p)
        v28 = struct.unpack_from(bo + "2f", data, p + 16)
        v30 = struct.unpack_from(bo + "2f", data, p + 24)
        ghv, f24 = struct.unpack_from(bo + "2f", data, p + 32)
        (count,) = struct.unpack_from(bo + "I", data, p + 40)
    except struct.error:
        raise FontError("truncated font fields at %d" % p)
    p += 44
    if p + count * _GLYPH_LEN != len(data):
        raise FontError(
            "%d glyph records of 27 bytes end at %d, the file at %d"
            % (count, p + count * _GLYPH_LEN, len(data))
        )
    glyphs = []
    for i in range(count):
        code, ox, oy, wd, u, v, uw, flag = struct.unpack_from(bo + "H6fB", data, p)
        p += _GLYPH_LEN
        g = {
            "code": code,
            "char": chr(code) if 32 <= code < 0xD800 else None,
            "offset": [ox, oy],
            "width": wd,
            "uv": [u, v],
            "u_width": uw,
            "flag": flag,
            "icon": bool(flag),  # drawn white with the current alpha (0x43efbb)
            # derived, pixels: [x, y, w, h] of the glyph cell in the atlas
            "rect_px": [round(u * w, 3), round(v * h, 3), round(uw * w, 3), gh],
        }
        glyphs.append(g)
    try:
        wx = _tex_fmt()
        tex["fmt"] = wx.TEX_FMT[en][0]
    except Exception:
        pass
    tex["data_offset"] = off
    tex["data_bytes"] = n
    doc = {
        "format": FORMAT,
        "evidence": "Font reader 0x540c6e, FontBuffer reader 0x44245e, descriptor 0x429e77",
        "order": bo,
        "has_data": True,
        "texture": tex,
        "glyph_height": gh,
        "b04": b04,
        "b38": b38,
        "b3c": b3c,
        "v28": list(v28),
        "v30": list(v30),
        "glyph_height_v": ghv,
        "f24": f24,
        "glyph_count": count,
        "fallback_code": FALLBACK_CODE,
        "glyphs": glyphs,
        "inferred": dict(INFERRED),
        "not_established": list(NOT_ESTABLISHED),
        "leftover_bytes": 0,
    }
    for name, alias in ALIASES:
        doc[name] = doc[alias]
    return doc


def pixels(data, doc):
    """The inline atlas block of `data` as parse() located it."""
    t = doc["texture"]
    return data[t["data_offset"] : t["data_offset"] + t["data_bytes"]]


def build(doc, pixel_block=b""):
    """The file bytes of a parse() result; `pixel_block` = pixels(data, doc)."""
    if not doc.get("has_data"):
        return b"\0"
    bo = doc["order"]
    t = doc["texture"]
    out = [b"\1"]
    out.append(
        struct.pack(
            bo + _DESC,
            t["width"],
            t["height"],
            t["enum"],
            _named(t, "usage", "x"),
            t["type"],
            int(t["alpha"]),
            t["mips"],
            t["size"],
        )
    )
    out.append(bytes(pixel_block))
    f = {name: _named(doc, name, alias) for name, alias in ALIASES}
    out.append(struct.pack(bo + "4I", doc["glyph_height"], f["flags"], f["h_align"], f["v_align"]))
    out.append(struct.pack(bo + "4f", *(list(f["spacing"]) + list(f["scale"]))))
    out.append(struct.pack(bo + "2f", doc["glyph_height_v"], f["fixed_advance"]))
    out.append(struct.pack(bo + "I", len(doc["glyphs"])))
    for g in doc["glyphs"]:
        out.append(
            struct.pack(
                bo + "H6fB",
                g["code"],
                g["offset"][0],
                g["offset"][1],
                g["width"],
                g["uv"][0],
                g["uv"][1],
                g["u_width"],
                g["flag"],
            )
        )
    return b"".join(out)


def atlas_image(data, doc):
    """Top mip of the atlas as a numpy array (h, w, 4) RGBA / (h, w) L8, or None when the
    format or platform layout is not decoded.  Uses the texture decoders of
    watchmen_extract (PC linear; Xbox 360 tiled; PS3 RSX)."""
    if not doc.get("has_data"):
        return None
    wx = _tex_fmt()
    t = doc["texture"]
    en, w, h = t["enum"], t["width"], t["height"]
    if en not in wx.TEX_FMT or t["type"] != 1:
        return None
    blk = pixels(data, doc)
    if doc["order"] == "<":
        return wx._decode_one_layer(blk, en, w, h)
    if t["size"]:
        return wx._x360_base_level(blk, en, w, h)
    return wx._ps3_layer_image(blk[36:], {"enum": en, "aw": w, "ah": h}, False)


def checks(doc):
    """Counts that test the inferred glyph fields against the atlas size:
    {glyphs, u_width_matches, whole_pixel_u, inside_atlas}."""
    if not doc.get("has_data"):
        return {"glyphs": 0, "u_width_matches": 0, "whole_pixel_u": 0, "inside_atlas": 0}
    w, h = doc["texture"]["width"], doc["texture"]["height"]
    gh = doc["glyph_height"]
    uw = wp = ins = 0
    for g in doc["glyphs"]:
        if abs(g["u_width"] * w - g["width"]) < 1e-3:
            uw += 1
        if abs(g["uv"][0] * w - round(g["uv"][0] * w)) < 1e-3:
            wp += 1
        x, y = g["uv"][0] * w, g["uv"][1] * h
        if x >= -1e-3 and y >= -1e-3 and x + g["width"] <= w + 1e-3 and y + gh <= h + 1e-3:
            ins += 1
    return {
        "glyphs": len(doc["glyphs"]),
        "u_width_matches": uw,
        "whole_pixel_u": wp,
        "inside_atlas": ins,
    }


def to_json(data, order=None):
    """parse() plus the `checks` block; a file that does not parse gives a marked stub
    (`not_decoded`) instead of raising."""
    try:
        doc = parse(data, order)
    except FontError as ex:
        return {
            "format": FORMAT,
            "not_decoded": "font: %s" % ex,
            "leftover_bytes": len(data),
        }
    doc["checks"] = checks(doc)
    return doc


def write_atlas(data, doc, png_path):
    """Write the atlas PNG; returns True when written (needs numpy + Pillow)."""
    try:
        from PIL import Image
    except Exception:
        return False
    img = atlas_image(data, doc)
    if img is None:
        return False
    Image.fromarray(img).save(str(png_path))
    return True


def notes(name, doc, atlas_written):
    """Log lines for one font (never silent about what was not decoded)."""
    if doc.get("not_decoded"):
        return ["WARNING: font %s not decoded: %s" % (name, doc["not_decoded"])]
    if not doc.get("has_data"):
        return ["note: font %s has no font buffer" % name]
    t = doc["texture"]
    out = [
        "font %s: %d glyphs, atlas %dx%d %s%s"
        % (
            name,
            doc["glyph_count"],
            t["width"],
            t["height"],
            t.get("fmt", "format %d" % t["enum"]),
            "" if atlas_written else " (atlas PNG NOT written)",
        )
    ]
    return out


if __name__ == "__main__":
    import json

    b = _read_bytes(sys.argv[1])
    d = to_json(b)
    print(json.dumps({k: v for k, v in d.items() if k != "glyphs"}, indent=1))
    if len(sys.argv) > 2 and d.get("has_data"):
        print("atlas written:", write_atlas(b, d, sys.argv[2]))
