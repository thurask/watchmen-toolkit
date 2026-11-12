"""Shared building blocks of the two GLB writers (variant_glb.write_glb,
rig_glb.build_rigged_glb): the glTF document with its packer, the rotation +
translation channel pair of one node, the skinned primitive.

The writers keep their own attribute orders, JOINTS_0 types, materials and
animation paths; this module holds only the blocks they write the same way, in
the order they write them, so the output of either writer does not change.
"""

import numpy as np

from wutil import GlbPacker, glb_bytes

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

    def add_attributes(self, pending, attributes):
        """`attributes` (a primitive's dict) with one float accessor per entry of
        `pending` ({name: (array, type)}, in its order; None = none), each array
        written as it is."""
        for name, (arr, typ) in (pending or {}).items():
            attributes[name] = self.accessor(
                self.view(np.ascontiguousarray(arr).tobytes(), ARRAY_BUFFER), FLOAT, len(arr), typ
            )
        return attributes

    def add_skinned_primitive(self, Vg, joints, SW, T, UV, pending, material, material_first):
        """A skinned triangle primitive (the dict, not yet appended to a mesh).

        Written in this order: POSITION of `Vg` (float32 (n, 3), with min / max),
        JOINTS_0 of `joints` (unsigned short (n, 4)), WEIGHTS_0 of `SW`, TEXCOORD_0
        of `UV`, the uint32 indices of `T`, then the `pending` attributes
        (add_attributes).  `material` is called for the material index: before the
        pending attributes when `material_first`, after them otherwise (a material
        that embeds its images the first time it is used puts their buffer views
        at that point)."""
        av, ac = self.view, self.accessor
        n = len(Vg)
        ap = ac(
            av(Vg.tobytes(), ARRAY_BUFFER), FLOAT, n, "VEC3", Vg.min(0).tolist(), Vg.max(0).tolist()
        )
        aj = ac(av(joints.tobytes(), ARRAY_BUFFER), UNSIGNED_SHORT, n, "VEC4")
        aw = ac(av(np.ascontiguousarray(SW).tobytes(), ARRAY_BUFFER), FLOAT, n, "VEC4")
        auv = ac(av(np.ascontiguousarray(UV).tobytes(), ARRAY_BUFFER), FLOAT, n, "VEC2")
        ai = ac(
            av(np.ascontiguousarray(T.astype(np.uint32)).tobytes(), ELEMENT_ARRAY_BUFFER),
            UNSIGNED_INT,
            T.size,
            "SCALAR",
        )
        mi = material() if material_first else None
        attributes = self.add_attributes(
            pending, {"POSITION": ap, "JOINTS_0": aj, "WEIGHTS_0": aw, "TEXCOORD_0": auv}
        )
        if not material_first:
            mi = material()
        return {"attributes": attributes, "indices": ai, "material": mi, "mode": 4}

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

    def finish(self):
        """The .glb bytes: frame.finish_gltf on the document, its one buffer
        entry, the two chunks."""
        import frame as _frame

        _frame.finish_gltf(self.j, self.bin)
        self.j["buffers"].append({"byteLength": len(self.bin)})
        return glb_bytes(self.j, self.bin)
