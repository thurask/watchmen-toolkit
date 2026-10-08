"""Fragment JSON: `nodes` / `named_instances` / `instances` / `transforms` come from
the exact parse, an unknown key's type guess cannot swallow the next record, and what
is guessed or not decoded is marked.

The sections used to come from a byte sweep of the raw file.  It took any
[key][n][printable bytes] for a string, so `m_tcompensatedirection = 1` followed by the
key of `m_ncompensatestart` (0x474F5F26, four printable bytes) and a zero read as the
text '&_OG' on PC and 'GO_&' on console; a name or a string cut by a chunk boundary
was lost, and a `localPos` whose value starts a new chunk was read one word early.

Synthetic fixtures only: every fragment below is built in the test, in both byte
orders and with the chunk boundaries the test needs."""

import os, struct, sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
import anim_state_machine as asm
import kapow_fragment as kf
import kapow_json as kj
import kapow_props as kp

H = kp.name_hash
UNK_A, UNK_B = 0xF89F0455, 0xCEACAED5  # in no table
ENTITY = ("logicalParent",)


class B:
    """Fragment bytes in one byte order."""

    def __init__(self, order):
        self.o = order

    def u(self, *v):
        return struct.pack(self.o + "%dI" % len(v), *v)

    def f(self, *v):
        return struct.pack(self.o + "%df" % len(v), *v)

    def s(self, text):
        b = text.encode("latin1") + b"\0"
        b += b"\0" * (-len(b) % 4)
        return self.u(len(b) // 4) + b

    def val(self, v):
        if isinstance(v, bool):
            return self.u(int(v))
        if isinstance(v, int):
            return self.u(v & 0xFFFFFFFF)
        if isinstance(v, float):
            return self.f(v)
        if isinstance(v, str):
            return self.s(v)
        if isinstance(v, list) and (not v or isinstance(v[0], str)):
            return self.u(len(v)) + b"".join(self.s(x) for x in v)
        return self.f(*v)

    def props(self, pairs):
        out = b""
        for k, v in pairs:
            key = k if isinstance(k, int) else H(k)
            if k in ENTITY:
                out += self.u(key) + (self.u(2) if v is None else self.u(3, v))
            else:
                out += self.u(key) + self.val(v)
        return out

    def type_record(self, nid, typ):
        return self.u(0xFFFFFFFF, nid) + self.s(typ)

    def instance(self, nid, pairs):
        return self.u(0xFFFFFFFE, nid) + self.props(pairs)

    def fragment(self, payload, cuts=()):
        """Header + the payload in chunks cut at the stream offsets `cuts`."""
        edges = [0] + sorted(cuts) + [len(payload)]
        chunks = [payload[a:b] for a, b in zip(edges, edges[1:]) if b > a]
        head = self.u(4) + bytes([0, 0]) + self.u(1) + b"\0" + bytes([0, 0])
        head += self.u(len(chunks))
        return head + b"".join(self.u(len(c)) + c for c in chunks)


def _state(b, cuts_at=None):
    """A fragment with two type records and three instances; returns (bytes, offsets
    of interest in the stream)."""
    at = {}
    p = b.type_record(0x10, "AnimationStateWM(Node)") + b.type_record(
        0x11, "CharacterHeadModel(Character)"
    )
    p += b.instance(0x10, [("name", "RunTurn180Right Combat"), ("logicalParent", None)])
    p += b.props([("siblingOrder", 1), ("m_tcompensatedirection", True)])
    p += b.props([("m_ncompensatestart", 0.0), ("m_smainbehavior", "Enemy")])
    at["second"] = len(p)
    p += b.u(0xFFFFFFFE, 0x11) + b.u(H("name"))
    at["in_name"] = len(p) + 8  # inside the characters of the name
    p += b.s("Dominatrix_1") + b.props([("logicalParent", 0x10), ("siblingOrder", 2)])
    p += b.u(H("localPos"))
    at["pos_value"] = len(p)
    p += b.f(1.5, 2.0, -3.25) + b.u(H("localOrient")) + b.f(0.0, 1.0, 0.0, 0.0)
    p += b.u(H("modelNames")) + b.val(["/art/a/Body.model", "", "/art/a/Hair.MODEL", "note"])
    p += b.u(H("textureSheetsDescription"))
    at["in_text"] = len(p) + 12
    p += b.s("2,0,0,0,/art/a/Body.bmp,5,1")
    p += b.instance(0x12, [("siblingOrder", 3), ("m_ssecondarybehavior", "")])
    cuts = [at[k] for k in (cuts_at or ())]
    return b.fragment(p, cuts), at


def _json(order, cuts_at=None):
    data, _ = _state(B(order), cuts_at)
    return kj.to_json("x.fragment", data, order=order)


def _text(j):
    """Every text value of `instances` (type records and resource lists included)."""
    return [v for i in j["instances"] for k, vals in i.items() if k[0] != "_" for v in vals]


def test_sweep_fixture_reproduces_the_fake_text():
    """The fixture is the real case: the sweep reads the next key hash as text."""
    for order, fake in (("<", "&_OG"), (">", "GO_&")):
        data, _ = _state(B(order))
        legacy = kj.fragment_json(data, order)
        got = [i.get("m_tcompensatedirection") for i in legacy["instances"]]
        assert [fake] in got


@pytest.mark.parametrize("order", ["<", ">"])
def test_no_integer_is_presented_as_text(order):
    j = _json(order)
    assert j["lossless"] and j["instances_source"] == "exact"
    text = _text(j)
    assert "&_OG" not in text and "GO_&" not in text
    for i in j["instances"]:
        for k in ("siblingOrder", "m_tcompensatedirection", "m_ncompensatestart", "logicalParent"):
            assert k not in i


def _agree(j):
    """(pairs of `instances` nodes_full does not back, text of nodes_full `instances`
    lacks) -- the owner of a node is the last `name` at or before it."""
    exp, owner = {}, None
    created = {}
    for n in j["nodes_full"]:
        for nm, t, v in n["props"]:
            if nm == "name":
                owner = v
        o = owner or "(preamble)"
        if n["created"] and n["type"]:
            created[n["id"]] = o
        for nm, t, v in n["props"]:
            if nm == "name":
                continue
            if t.rstrip("?") == "string":
                exp.setdefault(o, set()).add((nm, v))
            elif t.rstrip("?") == "list(string)":
                for x in v:
                    exp.setdefault(o, set()).add((nm, x))
                    kind = kf.ref_kind(x)
                    if kind:
                        exp.setdefault(o, set()).add((kind, x))
    for s in j["schema"]:
        exp.setdefault(created.get(s["id"], "(preamble)"), set()).add(("str_" + s["id"], s["type"]))
    got = {}
    for i in j["instances"]:
        for k, vals in i.items():
            if k not in ("name", "_transforms"):
                got.setdefault(i["name"], set()).update((k, v) for v in vals)
    owners = set(exp) | set(got)
    extra = sum(len(got.get(o, set()) - exp.get(o, set())) for o in owners)
    missing = sum(len(exp.get(o, set()) - got.get(o, set())) for o in owners)
    return extra, missing


@pytest.mark.parametrize("order", ["<", ">"])
@pytest.mark.parametrize("cuts", [None, ("in_name", "pos_value", "in_text")])
def test_instances_agree_with_nodes_full(order, cuts):
    j = _json(order, cuts)
    assert _agree(j) == (0, 0)
    # and the check itself sees the old section's faults
    data, _ = _state(B(order), cuts)
    old = dict(j, **kj.fragment_json(data, order))
    extra, missing = _agree(old)
    assert extra > 0 and missing > 0


def test_instances_content():
    j = _json("<")
    by = {i["name"]: i for i in j["instances"]}
    assert list(by) == ["(preamble)", "RunTurn180Right Combat", "Dominatrix_1"]
    assert by["(preamble)"] == {
        "name": "(preamble)",
        "str_00000010": ["AnimationStateWM(Node)"],
        "str_00000011": ["CharacterHeadModel(Character)"],
    }
    # the property's own name, not str_<hash>
    assert by["RunTurn180Right Combat"] == {
        "name": "RunTurn180Right Combat",
        "m_smainbehavior": ["Enemy"],
    }
    d = by["Dominatrix_1"]
    assert d["modelNames"] == ["/art/a/Body.model", "", "/art/a/Hair.MODEL", "note"]
    assert d["model_ref"] == ["/art/a/Body.model", "/art/a/Hair.MODEL"]  # list elements only
    assert d["textureSheetsDescription"] == ["2,0,0,0,/art/a/Body.bmp,5,1"]
    assert "texture_ref" not in d and "texture_table" not in d
    # a node without a name adds to the entry before it; an empty string is still text
    assert d["m_ssecondarybehavior"] == [""]
    assert list(d)[-1] == "_transforms"
    assert d["_transforms"] == [
        {"pos": [1.5, 2.0, -3.25], "quat": [0.0, 1.0, 0.0, 0.0], "yaw_deg": 180.0}
    ]
    assert j["named_instances"] == ["RunTurn180Right Combat", "Dominatrix_1"]
    assert j["transforms"] == [dict(d["_transforms"][0], name="Dominatrix_1")]
    assert [list(t)[0] for t in j["transforms"]] == ["name"]


def test_nodes_pair_a_type_with_its_own_id():
    j = _json(">")
    assert j["nodes"] == [
        {"type": "AnimationStateWM(Node)", "hash": "00000010"},
        {"type": "CharacterHeadModel(Character)", "hash": "00000011"},
    ]
    assert [(n["hash"], n["type"]) for n in j["nodes"]] == [
        (s["id"], s["type"]) for s in j["schema"]
    ]
    data, _ = _state(B(">"))
    # the sweep gave the first type the id of the record after it
    assert kj.fragment_json(data, ">")["nodes"][0]["hash"] == "00000011"


def test_byte_order_and_chunking_do_not_change_the_json():
    ref = _json("<")
    assert _json(">") == ref
    for order in ("<", ">"):
        for cuts in (
            ("in_name",),
            ("pos_value",),
            ("in_text",),
            ("second", "in_name", "pos_value"),
        ):
            j = _json(order, cuts)
            j["header"]["chunks"] = ref["header"]["chunks"]
            assert j == ref, (order, cuts)


def test_sweep_lost_what_a_chunk_boundary_cut():
    """What the old sections did with the same files (so the test above fails there)."""
    data, _ = _state(B("<"), ("in_name",))
    assert "Dominatrix_1" not in kj.fragment_json(data, "<")["named_instances"]
    data, _ = _state(B("<"), ("pos_value",))
    old = kj.fragment_json(data, "<")["transforms"]
    assert [1.5, 2.0, -3.25] not in [t["pos"] for t in old]


def test_created_node_type_record_is_listed_with_its_node():
    b = B("<")
    p = b.type_record(0x10, "Root(Node)") + b.instance(0x10, [("name", "Root")])
    p += b.type_record(0x20, "Folder") + b.props([("name", "Made"), ("siblingOrder", 1)])
    j = kj.to_json("x.fragment", b.fragment(p))
    by = {i["name"]: i for i in j["instances"]}
    assert by["(preamble)"] == {"name": "(preamble)", "str_00000010": ["Root(Node)"]}
    assert by["Made"] == {"name": "Made", "str_00000020": ["Folder"]}
    assert _agree(j) == (0, 0)
    roots, nodes = asm.tree_from_json(j)
    assert {n.cls for n in nodes.values()} == {"Root", "Folder"}


def test_empty_fragment_and_fallback_marker():
    b = B("<")
    j = kj.to_json("x.fragment", b.u(4) + bytes([0, 0]) + b.u(1) + b"\0" + bytes([0, 0]) + b.u(0))
    assert j["lossless"] and j["instances"] == [] and j["instances_source"] == "exact"
    assert kf.notes("x.fragment", j) == []
    # a string whose word count runs past the file: the exact parse stops there
    p = b.type_record(0x10, "Root(Node)") + b.instance(0x10, [("name", "Root")])
    p += b.u(H("m_smainbehavior"), 5000) + b"Enemy\0\0\0"
    j = kj.to_json("x.fragment", b.fragment(p))
    assert j["lossless"] is False and j["instances_source"] == "sweep"
    assert j["named_instances"] == ["Root"]  # the sweep's sections, kept and marked
    lines = kf.notes("Levels/x.fragment", j)
    assert len(lines) == 1 and "Levels/x.fragment" in lines[0] and "NOT decoded exactly" in lines[0]


# ---------------------------------------------------------------- unknown keys


def _waypoint(b, tail):
    p = b.type_record(0x10, "WaypointController(PivotNode)")
    p += b.instance(0x10, [("name", "wp"), ("m_nmaxdistance", 40.0)]) + tail
    p += b.instance(0x11, [("name", "next"), ("siblingOrder", 7)])
    return b.fragment(p)


@pytest.mark.parametrize("order", ["<", ">"])
def test_vector_guess_does_not_swallow_the_next_record(order):
    """[unknown][0.01][unknown][1]: read as ONE vector [0.01, -1448569344.0, 0.0] before."""
    b = B(order)
    r = kf.parse(_waypoint(b, b.u(UNK_A) + b.f(0.01) + b.u(UNK_B, 1)), order=order)
    assert r["ok"]
    assert r["inst"][0]["props"][2:] == [
        ("key_f89f0455", "raw4?", 0.01),
        ("key_ceacaed5", "raw4?", 1),
    ]
    assert r["unknown"] == {UNK_A: [1, "raw4"], UNK_B: [1, "raw4"]}
    assert r["inst"][1]["props"] == [("name", "string", "next"), ("siblingOrder", "integer", 7)]


def test_real_vector_of_an_unknown_key_is_still_a_vector():
    b = B("<")
    r = kf.parse(_waypoint(b, b.u(UNK_A) + b.f(1.0, -2.5, 0.0)))
    assert r["ok"] and r["inst"][0]["props"][2] == ("key_f89f0455", "vector?", [1.0, -2.5, 0.0])
    r = kf.parse(_waypoint(b, b.u(UNK_A) + b.f(0.0, 0.0, 0.0, 1.0)))
    assert r["inst"][0]["props"][2] == ("key_f89f0455", "quaternion?", [0.0, 0.0, 0.0, 1.0])


def test_vector_guess_refuses_a_key_hash_component():
    """A known key whose bits are an ordinary float (0x474F5F26 = 53087.15) is still a
    key, not a component: the record after the unknown key survives the lookahead."""
    assert kf.sane_float(struct.unpack("<f", struct.pack("<I", H("m_ncompensatestart")))[0])
    b = B("<")
    tail = b.u(UNK_A) + b.f(2.0) + b.u(UNK_B) + b.f(4.0)
    tail += b.props([("m_ncompensatestart", 3.0)]) + b.u(UNK_B) + b.f(5.0)
    r = kf.parse(_waypoint(b, tail))
    assert r["ok"]
    got = r["inst"][0]["props"][2:]
    assert ("m_ncompensatestart", "number", 3.0) in got
    assert all(not t.startswith(("vector", "quaternion")) for _, t, _ in got)


def test_sane_float():
    assert kf.sane_float(0.0) and kf.sane_float(-0.0) and kf.sane_float(0.01)
    assert kf.sane_float(-40000.0)
    for bits in (1, 0xCEACAED4, 0x7FC00000, 0x7F800000, 0xFFFFFFFE):
        assert not kf.sane_float(struct.unpack("<f", struct.pack("<I", bits))[0]), hex(bits)


def test_unknown_keys_are_marked_in_the_json_and_logged():
    b = B(">")
    data = _waypoint(b, b.u(UNK_A) + b.f(0.01) + b.u(UNK_B, 1))
    j = kj.to_json("x.fragment", data, order=">")
    assert j["lossless"] and j["instances_source"] == "exact"
    assert j["unknown_keys"] == [
        {"key": "key_ceacaed5", "count": 1, "type_guess": "raw4"},
        {"key": "key_f89f0455", "count": 1, "type_guess": "raw4"},
    ]
    lines = kf.notes("Levels/P/PartnerAI.fragment", j)
    assert len(lines) == 1
    assert "PartnerAI.fragment" in lines[0] and "key_f89f0455 as raw4 x1" in lines[0]
    assert "unknown_keys" not in _json("<") and kf.notes("x", _json("<")) == []


def test_part1_keys_are_named_and_typed():
    assert UNK_A not in kf.NAMES and UNK_B not in kf.NAMES
    assert len(kf.PART1_KEYS) == 7
    for h, (name, typ) in kf.PART1_KEYS.items():
        assert H(name) == h and kf.NAMES[h] == (name, typ)
    b = B(">")
    # the Part 1 WaypointController tail, in the order of the files
    tail = b.u(0x57A8BE19, 0xFFFFFFFF, 0x40CB4063, 0) + b.u(0x56EEC9BF) + b.f(0.5)
    tail += b.u(0xF89F0453) + b.f(0.01) + b.u(0xCEACAED4, 1)
    r = kf.parse(_waypoint(b, tail), order=">")
    assert r["ok"] and not r["unknown"]
    assert r["inst"][0]["props"][2:] == [
        ("_idebugrunthroughmode", "integer", 0xFFFFFFFF),
        ("_tdebugtmp01", "truth", False),
        ("_nsteplengthinmeters", "number", 0.5),
        ("_ntimeprstepinsec", "number", 0.01),
        ("_tuseteleport", "truth", True),
    ]
    p = b.type_record(0x10, "SoundEnvironment(CollisionBoxNode)")
    p += b.instance(0x10, [("name", "env")]) + b.u(0x0CDB31BF) + b.f(0.25)
    p += b.type_record(0x11, "visionblocker(MockupBox)")
    p += b.props([("name", "vb")]) + b.u(0xB29CF82F, 1)
    r = kf.parse(b.fragment(p), order=">")
    assert r["ok"] and not r["unknown"]
    assert r["inst"][0]["props"][1] == ("_nobstructionfactor", "number", 0.25)
    assert r["inst"][1]["props"][1] == ("_tstartenabled", "truth", True)


def test_parse_result_keeps_its_old_keys():
    data, _ = _state(B("<"))
    r = kf.parse(data)
    for k in ("ok", "fail", "schema", "inst", "unknown", "parsed_frac", "end", "size", "header"):
        assert k in r
    assert r["order"] == "<" and r["schema_lead"] == 2
    assert [len(a) for a in r["at"]] == [len(i["props"]) for i in r["inst"]]
    assert all(set(i) == {"node", "created", "props"} for i in r["inst"])
