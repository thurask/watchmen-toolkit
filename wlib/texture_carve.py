"""Texture assets to files: the layers a Texture header plans, cut from the
stream, decoded and written as PNGs (`<asset>/<j>_<label>_<WxH>_<FMT>.png`)
with `sheet.json` and `spec.txt` beside them (`carve_texture`; console streams
through `carve_texture_console`; PC cube maps level by level,
`PC_CUBE_LEVEL_MAJOR`).  The layers come from the exact header
(texture_header.read_texture_header); a header that does not read, or whose
layers do not tile the stream, is not decoded and gets a WARNING line.
"""

import os
import struct
import sys

from PIL import Image

# the flat wlib modules import each other by name (`import kapow_props`); one path
# setup for this module, also when it is run as a script or loaded by file path.
# Append, never insert(0): flat module names must not shadow the stdlib.
_WLIB = os.path.dirname(os.path.abspath(__file__))
if _WLIB not in sys.path:
    sys.path.append(_WLIB)
from wutil import order_name  # noqa: E402

import kapow_block  # noqa: E402
import texture_header  # noqa: E402
import texture_sheet  # noqa: E402
import texture_decode  # noqa: E402


def _console_prefix(frames, frame, faces, face):
    """File-name prefix of one console layer image, the PC carve's scheme:
    frameN_ for a frame of an animated texture, faceN_ for a cube face."""
    return ("frame%d_" % frame if frames > 1 else "") + ("face%d_" % face if faces > 1 else "")


def _save_layer_png(img, out_dir, prefix, j, label, lay):
    Image.fromarray(img).save(
        out_dir
        / (
            "%s%d_%s_%dx%d_%s.png"
            % (prefix, j, label, lay["aw"], lay["ah"], texture_header.TEX_FMT[lay["enum"]][0])
        )
    )


def _carve_x360_exact(stream, ex, out_dir, warn):
    """X360 carve from the exact header: every descriptor carries its stored byte
    size (parse_texture_frames `size`), so layers, animation frames and cube
    faces are located without any search.  Returns (png count, images per frame
    set, frame count), or None when the sizes do not add up to the stream.

    A cube layer stores its mip LEVELS one after another, each level holding the
    six faces (so face k of level 0 starts k * _x360_level0_bytes in); read that
    way all six faces equal the PS3 copy pixel for pixel (310/310 cube maps)."""
    sets = [[d for d in fr["slots"] if d] for fr in ex["frames"]]
    descs = [d for L in sets for d in L]
    if not descs or any(d["size"] <= 0 for d in descs):
        return None
    if sum(d["size"] for d in descs) != len(stream):
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    wrote = 0
    off = 0
    for f, L in enumerate(sets):
        for j, d in enumerate(L):
            en, w, h = d["enum"], d["aw"], d["ah"]
            faces = 6 if d["type"] == 2 else 1
            planned = texture_decode.x360_layer_bytes(en, w, h, d["mip"]) * faces
            if d["size"] != planned:
                warn(
                    "layer %d (%s %dx%d, %d mips) stores %d bytes, the layout rule gives %d: "
                    "top mip decoded from the layer start, not checked"
                    % (j, texture_header.TEX_FMT[en][0], w, h, d["mip"], d["size"], planned)
                )
            step = texture_decode.x360_level0_bytes(en, w, h)
            if faces > 1 and (min(w, h) < 32 or step * faces > d["size"]):
                warn(
                    "layer %d is a cube map smaller than 32 texels: where faces 1-5 sit in "
                    "the packed tail is not established, only face 0 written" % j
                )
                faces_out = 1
            else:
                faces_out = faces
            lbl = texture_header.texture_layer_label(L, j, ">")
            for k in range(faces_out):
                lo = off + k * step
                img = texture_decode.x360_base_level(stream[lo : off + d["size"]], en, w, h)
                if img is None:
                    warn(
                        "layer %d (%s %dx%d) not decoded" % (j, texture_header.TEX_FMT[en][0], w, h)
                        + (" (face %d)" % k if faces > 1 else "")
                        + (" (frame %d)" % f if len(sets) > 1 else "")
                    )
                    continue
                if lbl == "specSize" and img.ndim == 3:
                    # slot 7 is DXT1 here where PC and PS3 store L8: the red channel
                    # is that map (mean difference <= 8.4 on 88/88; green, blue and
                    # so the luma are not on TwilightLadyHair: 163 / 164 / 114)
                    img = img[:, :, 0].copy()
                _save_layer_png(img, out_dir, _console_prefix(len(sets), f, faces, k), j, lbl, d)
                wrote += 1
            off += d["size"]
    return wrote, len(sets[0]), len(sets)


def _carve_ps3_exact(stream, ex, segs, out_dir, warn):
    """PS3 carve from the exact header: one [36-byte RSX descriptor][data] segment
    per descriptor, in frame then slot order (937/937 and 1,190/1,190 textures).
    Returns (png count, images per frame set, frame count), or None when the
    segment count is not the descriptor count.

    A cube segment holds the six faces one after another, each a full mip chain
    (mip count = descriptor byte 13), every face but the last padded to 128
    bytes: face k starts k * align128(chain) in (310/310 segment sizes; all six
    faces equal the X360 copy pixel for pixel)."""
    sets = [[d for d in fr["slots"] if d] for fr in ex["frames"]]
    descs = [(f, j, L) for f, L in enumerate(sets) for j in range(len(L))]
    if not descs or len(descs) != len(segs):
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    wrote = 0
    for (f, j, L), (off, sz) in zip(descs, segs, strict=True):
        d = L[j]
        en, w, h = d["enum"], d["aw"], d["ah"]
        faces = 6 if d["type"] == 2 else 1
        starts = [0]
        if faces > 1:
            chain = texture_header.chain_bytes(en, w, h, stream[off - 36 + 13])
            pad = (chain + 127) & ~127
            if texture_header.TEX_FMT[en][1][0] == "blk" and 5 * pad + chain == sz:
                starts = [k * pad for k in range(6)]
            else:
                warn(
                    "layer %d is a cube map whose segment (%d bytes) is not six 128-byte "
                    "aligned mip chains of %d: only face 0 written" % (j, sz, chain)
                )
        normal = texture_header.is_normal_layer(L, j, ">")
        lbl = texture_header.texture_layer_label(L, j, ">")
        for k, st in enumerate(starts):
            img = texture_decode.ps3_layer_image(stream[off + st : off + sz], d, normal)
            if img is None:
                warn(
                    "layer %d (%s %dx%d) not decoded" % (j, texture_header.TEX_FMT[en][0], w, h)
                    + (" (face %d)" % k if faces > 1 else "")
                    + (" (frame %d)" % f if len(sets) > 1 else "")
                )
                continue
            _save_layer_png(img, out_dir, _console_prefix(len(sets), f, faces, k), j, lbl, d)
            wrote += 1
    return wrote, len(sets[0]), len(sets)


def carve_texture_console(stream, header, out_dir, log=None):
    """Console (X360/PS3) texture carve: decode the TOP mip of every layer to
    PNG.  The layer plan comes from the exact header (parse_texture_frames, big-
    endian) -- on X360 with each layer's stored size, on PS3 with one stream
    segment per layer; file names follow the PC carve (faceN_ / frameN_).  A
    stream that does not fit is cut by the header's frame-0 layers; that, a
    header that does not read, and every layer or face that could not be
    written, is logged as one
    "WARNING: texture <name>: ..." line and listed in sheet.json under
    TEXTURE_DECODE_KEY.  Returns #PNGs written > 0."""
    if not callable(log):
        log = lambda *a, **k: None
    try:
        ex = texture_header.read_texture_header(header, ">")
    except texture_header.TextureHeaderError as e:
        log(
            "      WARNING: texture %s: not decoded, the header does not read (%s)"
            % (out_dir.name, e)
        )
        return False
    name = texture_header.source_name(ex) or out_dir.name
    notes = []

    def warn(msg):
        notes.append(msg)
        log("      WARNING: texture %s: %s" % (name, msg))

    segs = texture_decode.ps3_segments(stream)
    res = _carve_x360_exact(stream, ex, out_dir, warn)
    if res is not None:
        wrote, nl, nf = res
        _write_spec_txt(header, out_dir)
        texture_sheet.mark_texture_decode(out_dir, notes)
        log(
            "      %s: X360 layers=%d x%d (exact stream %d) -> %s/ (%d png)"
            % (name, nl, nf, len(stream), out_dir.name, wrote)
        )
        return wrote > 0
    if segs is not None:
        res = _carve_ps3_exact(stream, ex, segs, out_dir, warn)
        if res is not None:
            wrote, nl, nf = res
            _write_spec_txt(header, out_dir)
            texture_sheet.mark_texture_decode(out_dir, notes)
            log("      %s: PS3 %d segs -> %s/ (%d png)" % (name, len(segs), out_dir.name, wrote))
            return wrote > 0
        warn(
            "%d stream segments for %d header layers: layer plan from the header's frame-0 layers"
            % (len(segs), sum(1 for fr in ex["frames"] for d in fr["slots"] if d))
        )
    else:
        sizes = sum(d["size"] for fr in ex["frames"] for d in fr["slots"] if d)
        warn(
            "header layer sizes add up to %d, the stream is %d bytes: layer plan from "
            "the header's frame-0 layers, layers may be missing" % (sizes, len(stream))
        )
    L = [d for d in ex["frames"][0]["slots"] if d]
    out_dir.mkdir(parents=True, exist_ok=True)
    wrote = 0
    if segs is not None:  # ---- PS3
        for j, (off, sz) in enumerate(segs):
            lay = L[j % len(L)]
            pre = "" if len(segs) == len(L) else "seg%d_" % (j // len(L))
            is_norm = texture_header.is_normal_layer(L, j % len(L), ">")
            img = texture_decode.ps3_layer_image(stream[off : off + sz], lay, is_norm)
            if img is None:
                warn("segment %d not decoded" % j)
                continue
            lbl = texture_header.texture_layer_label(L, j % len(L), ">")
            _save_layer_png(img, out_dir, pre, j % len(L), lbl, lay)
            wrote += 1
        _write_spec_txt(header, out_dir)
        texture_sheet.mark_texture_decode(out_dir, notes)
        log("      %s: PS3 %d segs -> %s/ (%d png)" % (name, len(segs), out_dir.name, wrote))
        return wrote > 0
    # ---- X360: byteswap + per-layer offset by size rule + untile the top mip
    sizes = [texture_decode.x360_layer_bytes(x["enum"], x["aw"], x["ah"], x["mip"]) for x in L]
    total = sum(sizes)
    reps = 1
    if total != len(stream):
        n = round(len(stream) / total) if total else 0
        if n >= 2 and n * total == len(stream):
            reps = n  # cube faces / anim frames
    off = 0
    for r in range(reps):
        for j, lay in enumerate(L):
            if off + 256 > len(stream):
                break
            img = texture_decode.x360_base_level(stream[off:], lay["enum"], lay["aw"], lay["ah"])
            if img is not None:
                pre = "" if reps == 1 else "seg%d_" % r
                _save_layer_png(
                    img, out_dir, pre, j, texture_header.texture_layer_label(L, j, ">"), lay
                )
                wrote += 1
            off += sizes[j]
    if total * reps != len(stream):
        warn(
            "frame-0 plan covers %d of %d stream bytes: layers may be missing or wrong"
            % (total * reps, len(stream))
        )
    _write_spec_txt(header, out_dir)
    texture_sheet.mark_texture_decode(out_dir, notes)
    log(
        "      %s: X360 layers=%d x%d (%s stream %d) -> %s/ (%d png)"
        % (
            name,
            len(L),
            reps,
            "exact" if total * reps == len(stream) else "approx",
            len(stream),
            out_dir.name,
            wrote,
        )
    )
    return wrote > 0


def _write_spec_txt(header, out_dir):
    """Console PBR specular params (exponent/intensity) -> spec.txt, matching
    the PC carve. The name-hash + float are byte-order-flipped, so read BE."""
    try:
        ex, it = texture_sheet.extract_specular(header, ">")
        if ex is not None or it is not None:
            with open(out_dir / "spec.txt", "w", encoding="utf-8", newline="\n") as _f:
                _f.write("%s %s" % ("" if ex is None else repr(ex), "" if it is None else repr(it)))
    except (OSError, struct.error, ValueError, IndexError) as e:
        texture_sheet.sheet_warning(out_dir, "spec.txt not written", e)
    texture_sheet.write_sheet_json(header, out_dir, ">")


#: PC cube maps: True = mip LEVELS one after another, six faces per level; False =
#: six face mip chains one after another (the files of releases before 1.4.0).
#: Measured: read level by level, all six faces of all 110 + 200 PC cube maps equal
#: the PS3 and X360 copies pixel for pixel; read face by face only face 0 does.
PC_CUBE_LEVEL_MAJOR = True


def carve_texture(stream, header, out_dir, log=None):
    """DETERMINISTIC carve: parse the layer plan from the header + the byte-exact
    stream length, then decode every layer (diffuse / normal / spec / ...) — or
    each cube face / animation frame — with NO coherence guessing.  A header
    that does not read, or whose layers do not tile the stream, writes nothing
    and one WARNING line.  An exception leaves with a note naming the texture,
    its sizes and its byte order."""
    try:
        return _carve_texture(stream, header, out_dir, log)
    except Exception as ex:
        ex.add_note(
            "texture %s: header %d bytes, stream %d bytes, %s"
            % (
                getattr(out_dir, "name", out_dir),
                len(header or b""),
                len(stream or b""),
                order_name(kapow_block.header_order_or_none(header)),
            )
        )
        raise


def _carve_texture(stream, header, out_dir, log):
    """carve_texture's body."""
    if not callable(log):
        log = lambda *a, **k: None
    S = len(stream)
    if S < 16:  # a bound of 256 would silently skip 12 tiny valid textures
        return False
    if not texture_header.is_texture_header(header, "<") and texture_header.is_texture_header(
        header, ">"
    ):
        return carve_texture_console(stream, header, out_dir, log)
    plan = texture_header.plan_texture_layers(header, S)
    if plan["kind"] == "fail":
        try:
            ex = texture_header.read_texture_header(header)
            why = "its layers do not tile the %d-byte stream once, six times or per frame" % S
            name = texture_header.source_name(ex) or out_dir.name
        except texture_header.TextureHeaderError as e:
            why, name = "the header does not read (%s)" % e, out_dir.name
        log("      WARNING: texture %s: not decoded, %s" % (name, why))
        return False
    out_dir.mkdir(parents=True, exist_ok=True)
    layers, kind, count = plan["layers"], plan["kind"], plan["count"]
    cb = lambda x: (
        x.get("chain") or texture_header.chain_bytes(x["enum"], x["aw"], x["ah"], x["mip"])
    )
    set_bytes = sum(cb(x) for x in layers)
    wrote = 0

    def dump_set(buf, prefix):
        nonlocal wrote
        off = 0
        for j, lay in enumerate(layers):
            en, w, h = lay["enum"], lay["aw"], lay["ah"]
            c = cb(lay)
            lb = buf[off : off + c]
            if lay.get("chain"):  # exact plan: linear rows carry the 4-byte pitch
                lb = texture_decode.unpad_linear(lb, en, w, h)
            img = texture_decode.decode_one_layer(lb, en, w, h)
            off += c
            if img is None:
                continue
            lbl = texture_header.texture_layer_label(layers, j)
            Image.fromarray(img).save(
                out_dir
                / ("%s%s_%s_%dx%d_%s.png" % (prefix, j, lbl, w, h, texture_header.TEX_FMT[en][0]))
            )
            wrote += 1

    match kind:
        case "single":
            dump_set(stream, "")
        case "cube":
            face = S // 6
            if PC_CUBE_LEVEL_MAJOR and plan.get("exact"):
                lay = layers[0]  # the exact plan admits one-layer cubes only
                lvl0 = texture_header.chain_bytes_exact(lay["enum"], lay["aw"], lay["ah"], 1)
                for f in range(6):
                    dump_set(stream[f * lvl0 : f * lvl0 + set_bytes], "face%d_" % f)
            else:
                for f in range(6):
                    dump_set(stream[f * face : (f + 1) * face], "face%d_" % f)
        case "anim":
            fr = S // count
            for f in range(count):
                dump_set(stream[f * fr : (f + 1) * fr], "frame%d_" % f)
    try:
        ex, it = texture_sheet.extract_specular(header)
        if ex is not None or it is not None:
            with open(out_dir / "spec.txt", "w", encoding="utf-8", newline="\n") as _f:
                _f.write("%s %s" % ("" if ex is None else repr(ex), "" if it is None else repr(it)))
    except Exception:
        pass
    texture_sheet.write_sheet_json(header, out_dir, "<")
    log(
        "      %s: %s x%d (set=%dB) layers=%d -> %s/ (%d png)"
        % (
            texture_header.source_name(texture_header.parse_texture_frames(header)) or out_dir.name,
            kind,
            count,
            set_bytes,
            len(layers),
            out_dir.name,
            wrote,
        )
    )
    return wrote > 0
