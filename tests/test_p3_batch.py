"""Pass 3 batch step: what the six-set export of 2026-10-05 showed to be wrong.

1. The `not_decoded.vertex_attributes` marker of a character GLB gave a reason that
   was true before the console and Part 1 header decode ("decoded from PC Part 2
   mesh buffers only"); the export wrote it into the two Rorschach GLBs of every
   console set, whose log line named the real cause.  Marker and log now agree.
"""

import os
import sys

import numpy as np

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))

import characters_export as ce  # noqa: E402
import variant_glb as vg  # noqa: E402


def _part(n, attrs):
    p = (np.zeros((n, 3), np.float32),)
    if not attrs:
        return p
    z = np.zeros((n, 3), np.float32)
    return vg.with_attrs(
        p, {"normal": z, "tangent": z, "bitangent": z, "color": np.zeros((n, 4), np.uint8)}
    )


def test_vertex_attribute_marker_names_the_real_causes():
    nd = ce.not_decoded_extras([[_part(3, False), _part(3, True)]])["not_decoded"]
    reason = nd["vertex_attributes"]["reason"]
    assert reason == ce.VERTEX_ATTRS_REASON
    # the case of variant_glb.buffer_vertex_attrs, as in the log line; a console
    # piece of unknown colour order keeps NORMAL / TANGENT and has its own marker
    assert "does not locate the vertex buffer" in reason
    assert "colour byte order is not known" in ce.VERTEX_COLOUR_REASON
    # no longer true since console and Part 1 headers are decoded
    assert "PC Part 2" not in reason and "older layout" not in reason
    assert "only" not in reason
