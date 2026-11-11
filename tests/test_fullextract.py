"""Found on the full `extract` of the Part 2 PC archive (2026-10-04)."""

import json

import kapow_fragment as kf
import kapow_json as kj
import kapow_props as kp
import text_assets as ta

import test_text_assets as tt
from conftest import kstr, u32s


def _fragment(payload):
    head = u32s(4) + bytes([0, 0]) + u32s(1) + b"\0" + bytes([0, 0]) + u32s(1)
    return head + u32s(len(payload)) + payload


def _inst(nid, name):
    return u32s(0xFFFFFFFE, nid) + u32s(kp.name_hash("name")) + kstr(name)


def test_type_records_at_the_head_keep_their_created_entries():
    """A model fragment opens with all its type records ("Model", "SubPivot": bare native
    names, no "Class(Native)" record anywhere) and the instance records follow.  The header
    parse took the whole run as the schema and dropped the `created` entries: 1,492 of them
    in 266 of the 906 Part 2 PC fragment JSONs, against 1.3.0 and docs/FRAGMENT_FORMAT.md."""
    ids = (0x5BC7CB2F, 0xDDF8F80C, 0x11223344)
    payload = b"".join(
        u32s(0xFFFFFFFF, i) + kstr(t) for i, t in zip(ids, ("Model", "SubPivot", "SubPivot"))
    )
    payload += b"".join(_inst(i, "n%d" % k) for k, i in enumerate(ids))
    data = _fragment(payload)
    r = kf.parse(data)
    assert r["ok"] and r["header"]["chunks"] == 1
    assert [(i["node"], i["created"], len(i["props"])) for i in r["inst"]] == [
        ("%08x" % i, True, 0) for i in ids
    ] + [("%08x" % i, False, 1) for i in ids]
    assert r["schema"] == [
        ("5bc7cb2f", "Model"),
        ("ddf8f80c", "SubPivot"),
        ("11223344", "SubPivot"),
    ]
    j = kj.to_json("m.fragment", data)
    assert [n["created"] for n in j["nodes_full"]] == [True] * 3 + [False] * 3
    assert all(n["type"] in ("Model", "SubPivot") for n in j["nodes_full"])
    assert j["header"]["version"] == 4 and j["lossless"]


def test_bare_records_in_front_of_a_class_record_still_go_to_the_schema_only():
    """Unchanged: with a "Class(Native)" record in the head, the bare native records in
    front of it are schema entries (1.3.0 skipped them) and add nothing to `inst`."""
    payload = u32s(0xFFFFFFFF, 0x10) + kstr("SceneNode")
    payload += u32s(0xFFFFFFFF, 0x12) + kstr("SceneScope(LoadBlock)")
    payload += _inst(0x10, "") + _inst(0x12, "L")
    r = kf.parse(_fragment(payload))
    assert r["schema"] == [("00000010", "SceneNode"), ("00000012", "SceneScope(LoadBlock)")]
    assert [(i["node"], i["created"]) for i in r["inst"]] == [
        ("00000010", False),
        ("00000012", False),
    ]


def test_text_index_names_the_block_the_same_from_an_archive_and_a_files_tree(tmp_path):
    """`extract` / `text game.naz` gave "derived_pc/.../x.block", `text FILES_DIR`
    "/derived_pc/.../x.block" (loose entries are named with a leading slash): the
    `block` of text/index.json was the only difference between the two outputs."""
    h, _s = tt.text_block()
    docs = []
    for k, name in enumerate(("derived_pc/levels/x.block", "/derived_pc/levels/x.block")):
        w = ta.TextWriter(str(tmp_path / str(k)))
        assert w.add_block(h, name) > 0
        w.write()
        with open(str(tmp_path / str(k) / "text" / "index.json"), encoding="utf-8") as fh:
            docs.append(json.load(fh))
    assert docs[0] == docs[1]
    blocks = {a["block"] for a in docs[0]["assets"].values()}
    assert blocks == {"derived_pc/levels/x.block"}
