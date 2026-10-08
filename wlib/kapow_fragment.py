#!/usr/bin/env python3
"""kapow_fragment — LOSSLESS .fragment parser (engine-verified, 2026-07-07).
Format (from executable decomp FUN_005473ee/FUN_00545e1b + TOD_tools):
  file = [header: u32 version, u8 singleton, u8 smartSelectable, u32 nameLen,
          name[nameLen] (NUL included), u8 reapplyable, u8 typed, u32 chunkCount
          -- engine Fragment::LoadHeader 0x54306d; 17 bytes with the empty name]
         + chunks
  chunk = [u32 size<=0x2800][payload]; payloads concatenate into ONE stream
  stream = type records [FFFFFFFF][nodeId][wc][TypeName] (script classes as
           "Class(Native)", native nodes as a bare "Folder"/"Model"/...; they open
           the stream AND recur between instances -- 0xFFFFFFFF is never followed
           by properties), and instances [FFFFFFFE][nodeId] then [keyHash][typed value]*
  keyHash = kapow_props.name_hash(name): bit-CRC32(poly 0x04C11DB7) over bytes & 0xDF
            (engine FUN_00423ce8; digits fold too, so NOT hash(name.upper()))
  types: number/integer/truth/color=4B; biginteger=8B; vector=12B; quaternion=16B;
         string=[wc][wc*4]; list(T)=[count][T*count];
         Entity: [tag] tag0/1/2=4B, tag3=[3][nodeId], tag4=[4][a][n][n words],
                 tag5=[5][n][n words]
  key names/types: game database.bin registry (3693) + TOD_tools builtins +
  exe strings; unknown keys are size-inferred with boundary/lookahead resync
  and reported with '?' type suffix.
Validation (2026-10): all 906 extracted fragments parse to EOF (9 of them are
17-byte header-only files = empty); 22 unknown-key occurrences remain corpus-wide
(was 580,286 before the name-hash fold fix, built-in property typing and
type-record handling); all 12777 resource-path strings present in the output.
"""

import struct, pickle, sys, re, math
import os as _os

_D = _os.path.dirname(_os.path.abspath(__file__))
if _D not in sys.path:
    sys.path.append(_D)  # append, never insert(0): flat module names must not shadow the stdlib
_KP = _os.path.join(_D, "kapow_fragment_keys.pkl")
try:
    with open(_KP, "rb") as _fh:
        _KD = pickle.load(_fh)
except OSError as _ex:
    # ImportError, NOT SystemExit (2026-08-17): a library module must not exit
    # the host process at import time -- SystemExit is a BaseException, so it
    # blew through every `except Exception` guard (pytest collection died with
    # zero tests run, and `import watchmenlib` killed interactive hosts).
    raise ImportError(
        "watchmen: missing data table %s (%s)\n"
        "  reinstall the package, or rebuild it with `watchmen gendata keys-import KEYS.json`"
        % (_KP, _ex)
    ) from _ex
h2t = _KD["keytable"]
std = _KD["stdkeys"]
STDTYPES = {
    "runScript": "truth",
    "open": "truth",
    "enabled": "truth",
    "visible": "truth",
    "runFrameUpdate": "truth",
    "smartSelectable": "truth",
    "logicalParent": "Entity",
    "siblingOrder": "integer",
}
NAMES = {}
for h, (n, t) in h2t.items():
    NAMES[h] = (n, t)
for h, n in std.items():
    NAMES[h] = (n, STDTYPES.get(n, "integer"))
for _h, _nt in _KD["promoted"].items():
    NAMES[_h] = _nt
# Part 1 script properties the key table (built from the Part 2 database) lacks.  Each
# name hashes to its key; the type is the control of the property in the class's
# registration in the Part 1 executables (UI strings beside waypointcontroller_tnt.cpp,
# soundenvironment_tnt.cpp and visionblocker_tnt.cpp in the PS3 p1.elf and the XBLA
# image), and the properties sit in the files in that registration's order.
# All seven are entries of the Part 1 database.bin (PC, the Xbox 360 devkit build and PS3)
# with exactly these spellings and types (wlib/script_database.py; docs/SCRIPT_DATABASE.md).
# Which class and caption a key belongs to is by file order, not read from registration code.
PART1_KEYS = {
    0x57A8BE19: (
        "_idebugrunthroughmode",
        "integer",
    ),  # WaypointController "Runthrough Special Mode"
    0x40CB4063: ("_tdebugtmp01", "truth"),  # WaypointController "Tjeck Waypoint Path" button
    0x56EEC9BF: ("_nsteplengthinmeters", "number"),  # WaypointController "Step Length(m)"
    0xF89F0453: ("_ntimeprstepinsec", "number"),  # WaypointController "Step Time(m/sec)"
    0xCEACAED4: ("_tuseteleport", "truth"),  # WaypointController "Use Teleport"
    0x0CDB31BF: ("_nobstructionfactor", "number"),  # SoundEnvironment "Obstruction factor"
    0xB29CF82F: ("_tstartenabled", "truth"),  # visionblocker "Start Enabled"
}
# PART1_KEYS whose SPELLING is inferred (key hash -> the property's caption in the
# registration's UI string): a name whose hash is exact but which is in no string list
# and no database.bin.  A fragment that uses one lists it under `inferred_names`
# (inferred_names()), so the JSON does not show a guess as a fact.  EMPTY since the
# Part 1 database.bin confirmed all seven spellings (five were listed here before); the
# mechanism stays for a name added later without such a source.
PART1_INFERRED = {}
INFERRED_NAMES = {}  # name -> (key hash, caption), only where PART1_KEYS supplies the name
for _h, _nt in PART1_KEYS.items():
    if _h not in NAMES and _h in PART1_INFERRED:
        INFERRED_NAMES[_nt[0]] = (_h, PART1_INFERRED[_h])
    NAMES.setdefault(_h, _nt)
NAMEABLE = _KD["nameable"]
NAME_KEY = 0x7282B2A2  # name
POS_KEY = 0x2F0823C4  # localPos
ROT_KEY = 0x51172879  # localOrient
# what a resource path among the elements of a list(string) is also listed as
REF_KINDS = (
    ("model_ref", (".model",)),
    ("texture_ref", (".bmp", ".tga")),
    ("fragment_ref", (".fragment",)),
    ("sound_ref", (".wav", ".ogg")),
    ("script_ref", (".tnt", ".script")),
    ("animation_ref", (".animation", ".animationgraph")),
    ("asset_ref", (".particle", ".sequence", ".pb", ".terrain", ".grass", ".detailmesh")),
)
# a type record's name: "Class(Native)" or a bare native class ("Folder", "Model")
NODERE = re.compile(r"^[A-Za-z_][A-Za-z_0-9 ]*(\([A-Za-z_0-9 ]*\))?$")
TYPERE = re.compile(r"^[A-Za-z_0-9 ]+\([A-Za-z_0-9 ]*\)$")


# native classes whose nodes host a fragment (FragmentNode and its subclasses, RTTI)
FRAGMENT_HOST_NATIVES = ("FragmentNode", "LoadBlock", "SceneNode", "StreamBlockNode")


def _read_bytes(path):
    """The file's bytes; the handle is closed before returning."""
    with open(path, "rb") as fh:
        return fh.read()


def parse_header(d, bo="<"):
    """The file header of a .fragment / .scene as fields, or None when `d` does
    not start with one (a bare stream).  Engine reader 0x54306d: version,
    singletonFragment, smartSelectable, fragmentName, reapplyable, typed, then
    the chunk count.  `size` is the header's length = where the chunks start."""
    if len(d) < 17:
        return None
    ver, sing, smart, nl = struct.unpack_from(bo + "IBBI", d, 0)
    if not (1 <= ver <= 16 and sing <= 1 and smart <= 1 and 1 <= nl <= 256):
        return None
    end = 10 + nl
    if end + 6 > len(d) or d[end - 1] != 0:
        return None
    name = d[10 : end - 1]
    if b"\x00" in name or any(c < 32 or c > 126 for c in name):
        return None
    reap, typed, chunks = struct.unpack_from(bo + "BBI", d, end)
    if reap > 1 or typed > 1 or chunks > 0x100000:
        return None
    return {
        "version": ver,
        "singleton": bool(sing),
        "smart_selectable": bool(smart),
        "name": name.decode("latin1"),
        "reapplyable": bool(reap),
        "typed": bool(typed),
        "chunks": chunks,
        "size": end + 6,
    }


def type_name_ok(d, q, bo="<"):
    """True when [wc][name] at q is a well-formed type-record name: exact word count,
    zero padding."""
    (wc,) = struct.unpack_from(bo + "I", d, q)
    raw = d[q + 4 : q + 4 + wc * 4]
    nm = raw.split(b"\x00")[0]
    return wc == len(nm) // 4 + 1 and not raw[len(nm) :].strip(b"\x00")


def dechunk(d, bo="<"):
    import struct as _s

    hd = parse_header(d, bo)
    # the exact header end first (a long fragmentName puts it beyond the old scan window)
    starts = ([hd["size"]] if hd else []) + list(range(8, 80))
    for start in starts:
        p = start
        parts = []
        while p + 4 <= len(d):
            sz = _s.unpack_from(bo + "I", d, p)[0]
            if not (0 < sz <= 0x2800) or p + 4 + sz > len(d):
                parts = None
                break
            parts.append(d[p + 4 : p + 4 + sz])
            p += 4 + sz
            if p == len(d):
                break
        if parts and p == len(d):
            return b"".join(parts), start
    return None, None


def _schema_scan(d, bo):
    """Return offset of first valid [FFFFFFFF][hash][wc][TypeName(...)] record, or None."""
    u = lambda o: struct.unpack_from(bo + "I", d, o)[0]
    scan = 0
    while scan + 16 <= min(len(d), 4096):
        if d[scan : scan + 4] == b"\xff\xff\xff\xff":
            wc = u(scan + 8)
            if 1 <= wc <= 40 and scan + 12 + wc * 4 <= len(d):
                nm = d[scan + 12 : scan + 12 + wc * 4].split(b"\x00")[0].decode("latin1", "replace")
                if TYPERE.match(nm):
                    return scan
        scan += 1
    return None


def detect_order(d):
    """Byte order of a .fragment: try chunk-size walk (only parses in the right
    order), fall back to the schema-record scan for unchunked payloads."""
    ok = [(bo, dechunk(d, bo)[0]) for bo in ("<", ">")]
    ok = [(bo, dc) for bo, dc in ok if dc is not None]
    if len(ok) == 2:
        # a small file can pass the chunk walk in the wrong order too (the walk ends
        # on the last byte by accident: SE_Countered_victim02.fragment, 393 bytes, on
        # console): the right order is the one whose payload holds a schema record
        for bo, dc in ok:
            if _schema_scan(dc, bo) is not None:
                return bo
    if ok:
        return ok[0][0]
    for bo in ("<", ">"):
        if _schema_scan(d, bo) is not None:
            return bo
    return "<"


def sane_float(x):
    """True for a float an unknown key's vector / quaternion guess may hold: zero, or a
    finite value of ordinary magnitude (an integer or a hash read as f32 is not)."""
    return x == x and (x == 0.0 or 1e-6 <= abs(x) <= 1e7)


def parse(d, collect_unknown=None, order=None):
    bo = order or detect_order(d)
    header = parse_header(d, bo)
    dc, st = dechunk(d, bo)
    if header is not None and st != header["size"] and not (dc is None and len(d) <= 17):
        header = None  # the chunk walk disagrees: not a header after all
    if dc is not None:
        d = dc
    u = lambda o: struct.unpack_from(bo + "I", d, o)[0]
    f = lambda o: struct.unpack_from(bo + "f", d, o)[0]
    # locate schema start: first valid [FFFFFFFF][hash][wc][TypeName(...)] record in the head
    p = None
    schema = []
    scan = 0
    while scan + 16 <= min(len(d), 4096):
        if d[scan : scan + 4] == b"\xff\xff\xff\xff":
            wc = u(scan + 8)
            if 1 <= wc <= 40 and scan + 12 + wc * 4 <= len(d):
                nm = d[scan + 12 : scan + 12 + wc * 4].split(b"\x00")[0].decode("latin1", "replace")
                if TYPERE.match(nm):
                    p = scan
                    break
        scan += 1
    # With a header the stream starts right behind it, so when the scan found a
    # "Class(Native)" record the type records with a bare native name ("SceneNode",
    # "FragmentNode") in front of it are read instead of skipped.  When it found none,
    # every record is a node's own: the main loop reads them, as it always did, and each
    # type record keeps its `created` entry in `inst`.
    lead = header is not None and dc is not None and p is not None
    if lead:
        p = 0
    if p is None:
        p = 0
        if dc is None and len(d) <= 17:
            # header-only file (17 bytes, no chunk follows): an EMPTY fragment
            # (9 SoundEvents/ForceTrigger files in Part 2), not a parse failure
            return dict(
                ok=True,
                fail=None,
                schema=[],
                inst=[],
                unknown={},
                parsed_frac=1,
                end=len(d),
                size=len(d),
                empty=True,
                header=header,
                order=bo,
                schema_lead=0,
                at=[],
            )
    # opening type records -> schema.  With a header the stream starts at 0 and may open
    # with bare native records ("SceneNode", "Folder"): they go to the schema too, up to
    # and including the first run of "Class(Native)" records, which is where the scan
    # used to start.  What follows is read by the main loop exactly as before, so the
    # order of `inst` (and with it the order of equal-siblingOrder children) is unchanged.
    while p + 12 <= len(d) and u(p) == 0xFFFFFFFF:
        wc = u(p + 8)
        if not (1 <= wc <= 40) or p + 12 + wc * 4 > len(d):
            break
        nm = d[p + 12 : p + 12 + wc * 4].split(b"\x00")[0].decode("latin1")
        if TYPERE.match(nm):
            lead = False
        elif not (lead and NODERE.match(nm) and type_name_ok(d, p + 8, bo)):
            break
        schema.append(("%08x" % u(p + 4), nm))
        p += 12 + wc * 4

    def type_name_at(q):
        """TypeName of a [wc][name\\0 pad] block at q (exact word count, zero
        padding, identifier-shaped), else None."""
        if q + 4 > len(d):
            return None
        wc = u(q)
        if not (1 <= wc <= 40) or q + 4 + wc * 4 > len(d):
            return None
        raw = d[q + 4 : q + 4 + wc * 4]
        nm = raw.split(b"\x00")[0]
        if wc != len(nm) // 4 + 1 or raw[len(nm) :].strip(b"\x00"):
            return None
        nm = nm.decode("latin1")
        return nm if NODERE.match(nm) else None

    schema_lead = len(schema)  # the opening type records (no instance record of their own)
    inst = []
    at = []  # per instance record: the stream offset of each property's value
    cur = None
    hard_fail = None
    unk_here = {}
    memo = {}

    def rdval(typ, p):
        if typ == "raw4":
            x = u(p)
            fl = f(p)
            v = (
                round(fl, 6)
                if (fl == fl and 1e-12 < abs(fl) < 1e12)
                else (x if x < 0x80000000 else x - 0x100000000)
            )
            return v, p + 4
        if typ == "number":
            return round(f(p), 6), p + 4
        if typ in ("integer", "int", "color", "netparticipant"):
            # netparticipant: one slot, default 0xFFFFFFFF (0x500343); in no shipped file
            return u(p), p + 4
        if typ == "biginteger":  # 8 bytes (datatype.cpp FUN_004facb7; pivotSheet_Id)
            return u(p) | (u(p + 4) << 32), p + 8
        if typ == "truth":
            return bool(u(p)), p + 4
        if typ == "vector":
            return [round(f(p + i * 4), 6) for i in range(3)], p + 12
        if typ == "quaternion":
            return [round(f(p + i * 4), 6) for i in range(4)], p + 16
        if typ == "string":
            wc = u(p)
            if wc > 4000 or p + 4 + wc * 4 > len(d):
                raise ValueError("wc %d" % wc)
            return d[p + 4 : p + 4 + wc * 4].split(b"\x00")[0].decode("latin1"), p + 4 + wc * 4
        if typ in ("Entity", "entity"):
            tag = u(p)
            if tag == 3:
                return {"ref": "%08x" % u(p + 4)}, p + 8
            if tag == 5:
                n = u(p + 4)
                if n > 64:
                    raise ValueError("etag5 n %d" % n)
                return {"xref": [("%08x" % u(p + 8 + i * 4)) for i in range(n)]}, p + 8 + n * 4
            if tag == 4:
                a = u(p + 4)
                n = u(p + 8)
                if n > 64:
                    raise ValueError("etag4 n %d" % n)
                return {
                    "xref4": [("%08x" % u(p + 12 + i * 4)) for i in range(n)],
                    "a": a,
                }, p + 12 + n * 4
            if tag in (0, 1, 2):
                return {"etag": tag}, p + 4
            raise ValueError("etag %d" % tag)
        if typ.startswith("list("):
            sub = typ[5:-1]
            cnt = u(p)
            q = p + 4
            if cnt > 50000:
                raise ValueError("cnt %d" % cnt)
            out = []
            for i in range(cnt):
                v, q = rdval(sub, q)
                out.append(v)
            return out, q
        raise ValueError("type %r" % typ)

    def guess(typ, p):
        """rdval for an UNKNOWN key's value.  A vector / quaternion guess is refused when
        a component is not a sane number or is itself a marker or a key hash: that is
        the next record, and taking it would swallow that record (Part 1
        WaypointController: [key][0.01][key][0] read as one vector)."""
        if typ in ("vector", "quaternion"):
            n = 3 if typ == "vector" else 4
            if p + 4 * n > len(d):
                raise ValueError("short")
            for i in range(n):
                w = u(p + 4 * i)
                if w in (0xFFFFFFFE, 0xFFFFFFFF) or w in NAMES or w in NAMEABLE:
                    raise ValueError("key hash inside a %s guess" % typ)
                if not sane_float(f(p + 4 * i)):
                    raise ValueError("not a number inside a %s guess" % typ)
        return rdval(typ, p)

    known_or_marker = lambda q: q == len(d) or (
        q + 4 <= len(d) and (u(q) in (0xFFFFFFFE, 0xFFFFFFFF) or u(q) in NAMES or u(q) in NAMEABLE)
    )
    # a typed stream (header byte `typed`; in no shipped file): a property is
    # [keyHash][typeHash][wordCount][value], and the value is wordCount words long
    # whatever the key (engine 0x545e1b, 0x53c5c3)
    typed_stream = bool(header and header.get("typed"))
    while p + 4 <= len(d):
        w = u(p)
        if w in (0xFFFFFFFE, 0xFFFFFFFF):
            if p + 8 > len(d):
                hard_fail = (p, "%08x" % w)
                break
            cur = {"node": "%08x" % u(p + 4), "created": w == 0xFFFFFFFF, "props": []}
            inst.append(cur)
            at.append([])
            p += 8
            if w == 0xFFFFFFFF:
                # type record in the instance stream: [wc][TypeName, NUL-padded to wc
                # words].  Reading it as properties desynced every created node.
                nm = type_name_at(p)
                if nm is not None:
                    schema.append((cur["node"], nm))
                    p += 4 + u(p) * 4
            continue
        if typed_stream:
            if p + 12 > len(d) or p + 12 + u(p + 8) * 4 > len(d):
                hard_fail = (p, "%08x typed value past the end" % w)
                break
            vs, q = p + 12, p + 12 + u(p + 8) * 4
            ent = NAMES.get(w)
            if ent is None:  # the frame gives the length: no guess is needed
                nm, typ, v = (
                    NAMEABLE.get(w, "key_%08x" % w),
                    "words?",
                    [u(o) for o in range(vs, q, 4)],
                )
                unk_here.setdefault(w, [0, "words"])
                unk_here[w][0] += 1
                if collect_unknown is not None:
                    collect_unknown.setdefault(w, {}).setdefault("words", 0)
                    collect_unknown[w]["words"] += 1
            else:
                nm, typ = ent
                try:
                    v, _ = rdval(typ, vs)
                except Exception as e:
                    hard_fail = (p, "%s:%s %s" % (nm, typ, e))
                    break
            if cur is None:
                cur = {"node": "(pre)", "props": []}
                inst.append(cur)
                at.append([])
            cur["props"].append((nm, typ, v))
            at[-1].append(vs)
            p = q
            continue
        ent = NAMES.get(w)
        if ent is None:
            # unknown key: infer value span; allow chains of unknown keys via depth-limited lookahead
            def try_ahead(q, depth):
                if known_or_marker(q):
                    return True
                if q in memo:
                    return memo[q]
                if depth <= 0 or q + 4 > len(d):
                    return False
                memo[q] = False
                for typ3 in ("Entity", "integer", "string", "vector", "quaternion"):
                    try:
                        _, q2 = guess(typ3, q + 4)
                    except Exception:
                        continue
                    if try_ahead(q2, depth - 1):
                        memo[q] = True
                        break
                return memo[q]

            def ascii_frac(a, b):
                seg = d[a:b]
                if not seg:
                    return 0
                return sum(1 for c in seg if 32 <= c < 127 or c == 0) / len(seg)

            order = [
                "raw4",
                "Entity",
                "string",
                "list(string)",
                "vector",
                "quaternion",
                "list(integer)",
            ]
            wc0 = u(p + 4) if p + 8 <= len(d) else 0
            if (
                1 <= wc0 <= 4000
                and p + 8 + wc0 * 4 <= len(d)
                and ascii_frac(p + 8, p + 8 + min(wc0 * 4, 64)) > 0.9
            ):
                order = ["string", "list(string)", "raw4", "Entity", "vector", "quaternion"]
            got = None
            # pass 1: immediate anchor
            for typ2 in order:
                try:
                    v, q = guess(typ2, p + 4)
                except Exception:
                    continue
                if known_or_marker(q):
                    got = (typ2, v, q)
                    break
            if got is None:
                for typ2 in order:
                    try:
                        v, q = guess(typ2, p + 4)
                    except Exception:
                        continue
                    if try_ahead(q, 200):
                        got = (typ2, v, q)
                        break
            if got is None:
                hard_fail = (p, "%08x" % w)
                break
            unk_here.setdefault(w, [0, got[0]])
            unk_here[w][0] += 1
            if collect_unknown is not None:
                collect_unknown.setdefault(w, {}).setdefault(got[0], 0)
                collect_unknown[w][got[0]] += 1
            if cur is None:
                cur = {"node": "(pre)", "props": []}
                inst.append(cur)
                at.append([])
            cur["props"].append((NAMEABLE.get(w, "key_%08x" % w), got[0] + "?", got[1]))
            at[-1].append(p + 4)
            p = got[2]
            continue
        nm, typ = ent
        try:
            v, q = rdval(typ, p + 4)
        except Exception as e:
            hard_fail = (p, "%s:%s %s" % (nm, typ, e))
            break
        if cur is None:
            cur = {"node": "(pre)", "props": []}
            inst.append(cur)
            at.append([])
        cur["props"].append((nm, typ, v))
        at[-1].append(p + 4)
        p = q
    return dict(
        ok=hard_fail is None,
        fail=hard_fail,
        schema=schema,
        inst=inst,
        unknown=unk_here,
        parsed_frac=p / len(d) if len(d) else 1,
        end=p,
        size=len(d),
        header=header,
        order=bo,
        schema_lead=schema_lead,
        at=at,
    )


def ref_kind(text):
    """The legacy `*_ref` key a resource path is listed under ('model_ref', ...), or None."""
    t = text.lower()
    for kind, exts in REF_KINDS:
        if t.endswith(exts):
            return kind
    return None


def sections(d, r):
    """`nodes`, `named_instances`, `instances` and `transforms` of the fragment JSON,
    built from the exact parse `r` = parse(d) -- never from a byte sweep of the file.

    A value is text only where the parser typed it `string` or `list(string)` (also as
    the marked guess `string?` of an unknown key), and it is listed under the name
    `nodes_full` gives that property.  The byte sweep these sections came from took any
    [key][n][printable bytes] for a string, so an integer followed by a key hash made of
    printable bytes read as text ('XdV/' under siblingOrder, the bytes reversed on
    console), and a string cut by a chunk boundary was lost.

    nodes       the type records in file order, {type, hash = the node id} (the same
                records as `schema`).  The sweep paired a type with the id of the record
                AFTER it and called the word count of that record's name `depth`.
    named_instances  every `name` value in file order.
    instances   one entry per instance NAME, in order of first appearance; nodes that
                share a name share the entry, a node without a `name` property adds to
                the entry of the node before it, and what precedes the first name (or
                belongs to a node with an empty name) is under "(preamble)".
                  <property>   the distinct text values of that property, in file order
                               (`name` itself is the entry's "name")
                  str_<id>     the type record of node <id>: ["Class(Native)"].  The
                               opening type table is under "(preamble)", the record of a
                               node created in the stream is under that node's name.
                  model_ref, texture_ref, fragment_ref, sound_ref, script_ref,
                  animation_ref, asset_ref
                               the resource paths among the ELEMENTS of list(string)
                               properties (`modelNames`), by extension -- they are also
                               under the list's own name
                  _transforms  one {pos, quat?, yaw_deg?} per `localPos`
    transforms  every `localPos` (finite) with its instance name; `quat` / `yaw_deg`
                when a unit `localOrient` follows it directly.
    """
    bo = r["order"]
    dc = dechunk(d, bo)[0]
    if dc is not None:
        d = dc
    f = lambda o: struct.unpack_from(bo + "f", d, o)[0]
    kname = NAMES[NAME_KEY][0]
    kpos = NAMES[POS_KEY][0]
    krot = NAMES[ROT_KEY][0]
    inst = {}
    order = []
    names = []
    tr = []

    def entry(owner):
        own = owner or "(preamble)"
        if own not in inst:
            inst[own] = {}
            order.append(own)
        return inst[own]

    def add(e, key, val):
        lst = e.setdefault(key, [])
        if val not in lst:
            lst.append(val)

    for h, t in r["schema"][: r["schema_lead"]]:
        add(entry(None), "str_" + h, t)
    typed = dict(r["schema"][r["schema_lead"] :])
    owner = None
    for rec, offs in zip(r["inst"], r["at"]):
        props = rec["props"]
        for nm, typ, v in props:
            if nm == kname and typ == "string":
                owner = v
                names.append(v)
                break
        e = entry(owner)
        if rec.get("created") and rec["node"] in typed:
            add(e, "str_" + rec["node"], typed[rec["node"]])
        for i, (nm, typ, v) in enumerate(props):
            base = typ[:-1] if typ.endswith("?") else typ
            if base == "string":
                if nm != kname:
                    add(e, nm, v)
            elif base == "list(string)":
                e.setdefault(nm, [])
                for x in v:
                    add(e, nm, x)
                for x in v:
                    kind = ref_kind(x)
                    if kind:
                        add(e, kind, x)
            elif nm == kpos and typ == "vector":
                o = offs[i]
                x, y, z = f(o), f(o + 4), f(o + 8)
                if not all(c == c and abs(c) != float("inf") for c in (x, y, z)):
                    continue
                t = {"name": owner, "pos": [round(x, 3), round(y, 3), round(z, 3)]}
                if i + 1 < len(props) and props[i + 1][0] == krot and offs[i + 1] == o + 16:
                    qq = [f(o + 16 + 4 * k) for k in range(4)]
                    if 0.98 < sum(c * c for c in qq) < 1.02:
                        t["quat"] = [round(c, 4) for c in qq]
                        t["yaw_deg"] = round(math.degrees(2 * math.atan2(qq[1], qq[3])), 1)
                tr.append(t)
                e.setdefault("_transforms", []).append({k: w for k, w in t.items() if k != "name"})
    out = []
    for k in order:
        e = dict(inst[k])
        t = e.pop("_transforms", None)
        if t is not None:
            e["_transforms"] = t  # last, as it always was
        out.append({"name": k, **e})
    return {
        "nodes": [{"type": t, "hash": h} for h, t in r["schema"]],
        "named_instances": names,
        "instances": out,
        "transforms": tr,
    }


def unknown_keys(r):
    """[{key, count, type_guess}] for the keys of parse result `r` that are in no table:
    their value type is inferred from the bytes (marked '?' in `nodes_full`)."""
    return [
        {"key": NAMEABLE.get(h, "key_%08x" % h), "count": n, "type_guess": t}
        for h, (n, t) in sorted(r["unknown"].items())
    ]


def inferred_names(r):
    """[{name, key, count, confidence, caption}] for the properties of parse result `r`
    whose NAME is an inferred spelling (PART1_INFERRED): the key hash and the value are
    read from the file, the spelling of the name is not established.  Empty for every
    fragment that uses none, which is every file while PART1_INFERRED is empty."""
    n = {}
    for i in r["inst"]:
        for p in i["props"]:
            if p[0] in INFERRED_NAMES:
                n[p[0]] = n.get(p[0], 0) + 1
    return [
        {
            "name": k,
            "key": "%08x" % INFERRED_NAMES[k][0],
            "count": n[k],
            "confidence": "inferred",
            "caption": INFERRED_NAMES[k][1],
        }
        for k in sorted(n)
    ]


INFERRED_NAMES_NOTE = (
    "the spelling of these property names is inferred: each hashes to the key stored in "
    "the file and matches the caption of the property in the Part 1 executables, but the "
    "name itself is in no string list and no database.bin (docs/FRAGMENT_FORMAT.md, "
    "'Part 1 keys'); key, type and value are as stored"
)


def notes(name, j):
    """Log lines for one fragment JSON `j` (kapow_json.to_json): what was not decoded
    exactly.  Empty for a fully typed, losslessly parsed fragment."""
    out = []
    if not j.get("lossless"):
        why = j.get("parse_error") or "the property stream does not parse to its end"
        out.append(
            "WARNING: fragment %s: NOT decoded exactly (%s); instances / transforms are the"
            " byte-sweep fallback and may hold wrong text" % (name, why)
        )
    uk = j.get("unknown_keys")
    if uk:
        out.append(
            "WARNING: fragment %s: %d value(s) of %d unknown key(s) typed by guess: %s"
            % (
                name,
                sum(k["count"] for k in uk),
                len(uk),
                ", ".join("%s as %s x%d" % (k["key"], k["type_guess"], k["count"]) for k in uk),
            )
        )
    return out


if __name__ == "__main__":
    d = _read_bytes(sys.argv[1])
    r = parse(d)
    print(
        "ok:",
        r["ok"],
        "frac %.4f" % r["parsed_frac"],
        "schema:",
        len(r["schema"]),
        "inst:",
        len(r["inst"]),
        "unknown keys:",
        len(r["unknown"]),
    )
    if r["fail"]:
        print("FAIL:", r["fail"])
    for i in r["inst"]:
        print("node", i["node"], "C" if i.get("created") else "", len(i["props"]), "props")
