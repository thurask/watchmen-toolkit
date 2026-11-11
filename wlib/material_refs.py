"""What a model says about its materials: the textures of the ModelRes header
material list (`extract_materials`, one `TexRef` per render submesh), the
material index of each submesh (`submesh_materials`), a texture asset path as
a reference (`texture_ref`) and as the key a TextureIndex files it under
(`texture_key`), and the bare name of a path (`material_stem`).
"""

import os
import re
import struct
import sys

import numpy as np

# the flat wlib modules import each other by name (`import kapow_props`); one path
# setup for this module, also when it is run as a script or loaded by file path.
# Append, never insert(0): flat module names must not shadow the stdlib.
_WLIB = os.path.dirname(os.path.abspath(__file__))
if _WLIB not in sys.path:
    sys.path.append(_WLIB)
import extract_paths  # noqa: E402


def _u32le(b, o):
    return struct.unpack_from("<I", b, o)[0]


def u32_at(b, o, bo="<"):
    return struct.unpack_from(bo + "I", b, o)[0]


_TEX_RE = re.compile(rb"/[ -~]*?\.(?:bmp|tga|dds|png|jpg)", re.I)


def texture_key(path):
    """Asset path -> the key it has in a TextureIndex: '/'-separated, lower case, no
    leading slash, the same parts `safe()` keeps ('' / '.' / '..' dropped, ':' -> '_')."""
    parts = [p for p in str(path).replace("\\", "/").split("/") if p not in ("", ".", "..")]
    return "/".join(p.replace(":", "_") for p in parts).lower()


class TexRef(str):
    """A material name that remembers the texture ASSET PATH its model stores.

    The model header lists full paths ('/art/characters/bikers/textures/head.bmp',
    ModelRes::Read 0x547006) and the engine loads exactly that asset (0x49b2b2 ->
    AssetManager 0x55243f); the bare name ('head') is not unique in the game data.
    It still reads, prints and compares like the plain name, but two TexRefs with
    different paths are different materials (dict / set keys included)."""

    __slots__ = ("path",)

    def __new__(cls, name, path=None):
        o = str.__new__(cls, name)
        o.path = path or None
        return o

    def __eq__(self, other):
        if not str.__eq__(self, other):
            return False
        po = getattr(other, "path", None)
        return not (self.path and po) or texture_key(self.path) == texture_key(po)

    def __ne__(self, other):
        return not self.__eq__(other)

    __hash__ = str.__hash__

    def __reduce__(self):
        return (TexRef, (str(self), self.path))


def texture_ref(path):
    """Texture asset path -> TexRef(bare name, path).

    With --names canonical (default) the path is first given its canonical
    spelling (canonical_names.canonical: the shipped table, and during an
    `extract` the spelling the texture was written under), so a material is
    named like the texture folder it resolves to whatever letter case the
    referring model stores."""
    path = extract_paths.names_module().canonical(path)
    return TexRef(material_stem(path), path)


def extract_materials(header):
    """Ordered texture names from the ModelRes header material list (one per
    render submesh, in submesh order, for character/prop models).  Each is a
    TexRef: the bare name, with the full asset path in `.path`."""
    out = []
    for m in _TEX_RE.finditer(header):
        out.append(texture_ref(m.group().decode("latin1")))
    return out


def _u32_all(header, order="<"):
    """numpy uint32 array W with W[o] = the u32 at byte offset o, for every o with
    four bytes left (one view per byte phase, interleaved)."""
    n = len(header) - 3
    if n <= 0:
        return np.zeros(0, np.uint32)
    W = np.empty(n, np.uint32)
    dt = np.dtype(order + "u4")
    for ph in range(4):
        k = (len(header) - ph) // 4
        W[ph::4] = np.frombuffer(header, dt, count=k, offset=ph)[: len(W[ph::4])]
    return W


def _descriptor_candidates(header, order="<"):
    """Offsets p (0 <= p < len - 24) that pass the geometry-descriptor test of
    find_descriptors: [fa][nv][G 5|6][fb = fa, 0|8][ib even 6..8e6][1].
    Vectorised over every byte offset."""
    n = len(header)
    if n - 24 <= 0:
        return []
    W = _u32_all(header, order)
    m = n - 24
    fa, nv, G, fb, ib, one = (W[k : k + m] for k in (0, 4, 8, 12, 16, 20))
    ok = (
        ((G == 5) | (G == 6))
        & (fa == fb)
        & ((fa == 0) | (fa == 8))
        & (one == 1)
        & (nv >= 3)
        & (nv <= 300000)
        & (ib >= 6)
        & (ib <= 8000000)
        & (ib % 2 == 0)
    )
    return np.nonzero(ok)[0].tolist()


def submesh_materials(header, order="<"):
    """Per-submesh material indices, in submesh (descriptor) order.

    Engine layout (verified on Rorschach vs in-Blender ground truth): each
    render-piece record is
        [u32 len][pieceName..\0] ... [u32 1][u32 materialIndex] ... [geometry descriptor]
    i.e. the NAME+MATERIAL precede their descriptor.  Positional pairing with
    extract_materials() order is WRONG whenever one material covers several
    submeshes (Rorschach trenchcoat).  Returns list of (pieceName, matIndex),
    one per descriptor; matIndex indexes extract_materials(header)."""
    nmats = len(extract_materials(header))
    recs = []
    i = 0
    n = len(header)
    # offsets whose u32 can be a name length 2..48: only these need the record
    # test, every other offset just steps on
    lenpat = re.compile(
        (rb"(?=[\x02-\x30]\x00\x00\x00)" if order == "<" else rb"(?=\x00\x00\x00[\x02-\x30])"),
        re.S,
    )
    while i < n - 8:
        m = lenpat.search(header, i, n - 8 + 3)
        if m is None or m.start() >= n - 8:
            break
        i = m.start()
        ln = u32_at(header, i, order)
        if 2 <= ln <= 48 and i + 4 + ln <= n:
            sb = header[i + 4 : i + 4 + ln]
            if sb[-1] == 0 and all(32 <= c < 127 for c in sb[:-1]) and sb[:1].isalpha():
                for o in range(i + 4 + ln, min(i + 4 + ln + 24, n - 8), 4):
                    a, b = u32_at(header, o, order), u32_at(header, o + 4, order)
                    if a == 1 and b < max(nmats, 1):
                        recs.append((i, sb[:-1].decode("latin1"), b))
                        break
                i += 4 + ln
                continue
        i += 1
    # descriptor positions (same predicate as find_descriptors)
    dpos = []
    last = -100
    for p_ in _descriptor_candidates(header, order):
        fa = u32_at(header, p_, order)
        nv = u32_at(header, p_ + 4, order)
        G = u32_at(header, p_ + 8, order)
        fb = u32_at(header, p_ + 12, order)
        ib = u32_at(header, p_ + 16, order)
        one = u32_at(header, p_ + 20, order)
        if (
            G in (5, 6)
            and fa == fb
            and fa in (0, 8)
            and one == 1
            and 3 <= nv <= 300000
            and 6 <= ib <= 8000000
            and ib % 2 == 0
        ):
            if p_ - last >= 24:
                dpos.append(p_)
                last = p_
    out = []
    for k, dp in enumerate(dpos):
        prev = [r for r in recs if r[0] < dp]
        out.append((prev[-1][1], prev[-1][2]) if prev else ("sub%d" % k, k if k < nmats else 0))
    return out


def material_stem(path):
    return path.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]
