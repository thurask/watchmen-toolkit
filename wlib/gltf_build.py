"""Shared building blocks of the two GLB writers (variant_glb.write_glb,
rig_glb.build_rigged_glb): the glTF document with its packer, the rotation +
translation channel pair of one node, the skinned primitive.

The writers keep their own attribute orders, JOINTS_0 types, materials and
animation paths; this module holds only the blocks they write the same way, in
the order they write them, so the output of either writer does not change.
"""

import numpy as np

from wutil import GlbPacker

#: glTF constants used below
FLOAT = 5126
UNSIGNED_SHORT = 5123
UNSIGNED_INT = 5125
ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963


class GltfDoc:
    """A glTF document (`j`, a dict) and its binary buffer (`bin`, through
    `packer`, a wutil.GlbPacker on the document's bufferViews / accessors).

    asset: the `asset` object.  lists: the names of the top-level lists after
    "asset", "scene" and "scenes", in document order (they must include
    "bufferViews" and "accessors").  sampler: the one default sampler, written
    last as "samplers".  The key order is the order of the JSON chunk."""

    def __init__(self, asset, lists, sampler):
        j = {"asset": asset, "scene": 0, "scenes": [{"nodes": []}]}
        for k in lists:
            j[k] = []
        j["samplers"] = [sampler]
        self.j = j
        self.packer = GlbPacker(j["bufferViews"], j["accessors"])
        self.bin = self.packer.bin

    def view(self, data, target=None):
        """GlbPacker.view: index of a bufferView holding `data`."""
        return self.packer.view(data, target)

    def accessor(self, bv, ct, count, typ, mn=None, mx=None, normalized=False):
        """GlbPacker.accessor: index of an accessor of view `bv`."""
        return self.packer.accessor(bv, ct, count, typ, mn, mx, normalized)

    def float_accessor(self, arr, typ, target=None):
        """A float32 accessor (no min / max) of `arr`, one element per row."""
        arr = np.asarray(arr, np.float32)
        return self.accessor(self.view(arr.tobytes(), target), FLOAT, len(arr), typ)

    def add_trs(self, sm, chn, node, input_acc, Q, T):
        """The rotation and translation channels of `node`: the VEC4 rotation
        accessor of `Q` (K, 4), the VEC3 translation accessor of `T` (K, 3), both
        float32, then the rotation sampler and channel, then the translation
        sampler and channel, LINEAR on the time accessor `input_acc`; appended to
        the animation's `sm` (samplers) and `chn` (channels)."""
        vo = self.float_accessor(Q, "VEC4")
        to = self.float_accessor(T, "VEC3")
        sm.append({"input": input_acc, "output": vo, "interpolation": "LINEAR"})
        chn.append({"sampler": len(sm) - 1, "target": {"node": node, "path": "rotation"}})
        sm.append({"input": input_acc, "output": to, "interpolation": "LINEAR"})
        chn.append({"sampler": len(sm) - 1, "target": {"node": node, "path": "translation"}})
