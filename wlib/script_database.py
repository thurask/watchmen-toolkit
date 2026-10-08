#!/usr/bin/env python3
"""script_database -- reader for the baked script name database (`database.bin`).

The engine loads `/data/tnt/production/Database.bin` (remapped under `/data_baked` by
0x4ef41c; call at 0x820e5b) with the loader 0x47c5f5:

    u32 nProps
    nProps x [u32 len; char[len]]      "name:type", registered by 0x4ee06a
    u32 nMessages
    nMessages x [u32 len; char[len]]   "signature" or "signature:returntype", by 0x4ef657

Read from the code: both loops refuse an entry when `len + 1 > 0x3ff` (unsigned), so the
largest accepted length is 0x3fe; the id of an entry is the engine name hash
(0x423d30 = `kapow_props.name_hash` of the text before the first ':').  Read from the
data (six retail files): `len` counts the terminating NUL, the words are little-endian
on every platform (the reader still detects the order), and the file ends with the last
message.

    db = script_database.load(path)          # or parse(bytes)
    db["properties"][i] == {"index", "name", "type", "hash"}
    db["messages"][i]   == {"index", "text", "name", "args", "returns", "hash"}
    db["exact"]         # True when the file was consumed exactly

`compare_names(db)` sets the property names against the toolkit's own name tables.
"""

import json
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)  # append, never insert(0)

import kapow_props  # noqa: E402

FORMAT = "kapow-script-database/1"
MAX_LEN = 0x3FE  # 0x47c5f5: `len + 1 > 0x3ff` aborts the load


class DatabaseError(ValueError):
    """The bytes do not follow the database layout."""


def _walk(data, bo):
    """Both sections read with byte order `bo`: (props, messages, end offset).
    Raises DatabaseError where the engine would abort or the data runs out."""
    pos = 0
    sections = []
    for label in ("property", "message"):
        if pos + 4 > len(data):
            raise DatabaseError("%s count at %d is past the end" % (label, pos))
        (count,) = struct.unpack_from(bo + "I", data, pos)
        pos += 4
        if count > (len(data) - pos) // 4:
            raise DatabaseError("%s count %d does not fit the file" % (label, count))
        rows = []
        for i in range(count):
            if pos + 4 > len(data):
                raise DatabaseError("%s %d: length at %d is past the end" % (label, i, pos))
            (ln,) = struct.unpack_from(bo + "I", data, pos)
            pos += 4
            if ln > MAX_LEN:
                raise DatabaseError("%s %d: length 0x%x above 0x%x" % (label, i, ln, MAX_LEN))
            if pos + ln > len(data):
                raise DatabaseError("%s %d: text at %d is past the end" % (label, i, pos))
            rows.append(data[pos : pos + ln])
            pos += ln
        sections.append(rows)
    return sections[0], sections[1], pos


def detect_order(data):
    """'<' or '>': the byte order under which the whole file walks; the order that
    consumes it exactly wins.  Raises DatabaseError when neither walks."""
    best = None
    err = None
    for bo in ("<", ">"):
        try:
            end = _walk(data, bo)[2]
        except DatabaseError as ex:
            err = err or ex
            continue
        if end == len(data):
            return bo
        best = best or bo
    if best is None:
        raise DatabaseError("not a script database: %s" % err)
    return best


def _text(raw):
    """Entry bytes as text: cut at the first NUL (the stored length counts it)."""
    return raw.split(b"\x00", 1)[0].decode("latin1")


def split_signature(sig):
    """`name(arg,list(T),...)` -> (name, [arg types]); a bare name has args None."""
    if "(" not in sig or not sig.endswith(")"):
        return sig, None
    name, inner = sig.split("(", 1)
    inner = inner[:-1]
    args = []
    depth = 0
    cur = ""
    for ch in inner:
        if ch == "," and depth == 0:
            args.append(cur)
            cur = ""
            continue
        depth += ch == "("
        depth -= ch == ")"
        cur += ch
    if cur or args:
        args.append(cur)
    return name, args


def parse(data, order=None):
    """Parse database bytes.  `order` forces '<' or '>' (default: detect)."""
    bo = order or detect_order(data)
    props, msgs, end = _walk(data, bo)
    out_props = []
    for i, raw in enumerate(props):
        s = _text(raw)
        name, _, typ = s.partition(":")
        out_props.append(
            {
                "index": i,
                "name": name,
                "type": typ if ":" in s else None,
                "hash": "%08x" % kapow_props.name_hash(name),
            }
        )
    out_msgs = []
    for i, raw in enumerate(msgs):
        s = _text(raw)
        sig, _, ret = s.partition(":")
        name, args = split_signature(sig)
        out_msgs.append(
            {
                "index": i,
                "text": s,
                "name": name,
                "args": args,
                "returns": ret if ":" in s else None,
                "hash": "%08x" % kapow_props.name_hash(sig),
            }
        )
    unterminated = sum(1 for raw in props + msgs if not raw.endswith(b"\x00"))
    return {
        "format": FORMAT,
        "byte_order": "little" if bo == "<" else "big",
        "size": len(data),
        "consumed": end,
        "exact": end == len(data),
        "property_count": len(out_props),
        "message_count": len(out_msgs),
        "unterminated_entries": unterminated,
        "evidence": (
            "layout and length limit read from the loader 0x47c5f5; ids are the name hash "
            "0x423d30 of the text before ':' (0x4edfa4, 0x4ef571)"
        ),
        "properties": out_props,
        "messages": out_msgs,
    }


def load(path, order=None):
    with open(path, "rb") as fh:
        return parse(fh.read(), order)


def build(props, messages, order="<"):
    """Database bytes from `props` ("name:type" strings) and `messages` (signature
    strings); each entry is stored with its NUL as the retail files do."""
    out = [struct.pack(order + "I", len(props))]
    for sec in (props, messages):
        if sec is messages:
            out.append(struct.pack(order + "I", len(messages)))
        for s in sec:
            raw = s.encode("latin1") + b"\x00"
            if len(raw) > MAX_LEN:
                raise DatabaseError("entry longer than 0x%x" % MAX_LEN)
            out.append(struct.pack(order + "I", len(raw)) + raw)
    return b"".join(out)


def type_histogram(db):
    """{type: count} over the properties, most frequent first."""
    hist = {}
    for p in db["properties"]:
        hist[p["type"]] = hist.get(p["type"], 0) + 1
    return dict(sorted(hist.items(), key=lambda kv: (-kv[1], str(kv[0]))))


def by_hash(db, section="properties"):
    """{hash int: [entries]} of one section (a hash can have several spellings)."""
    out = {}
    for e in db[section]:
        out.setdefault(int(e["hash"], 16), []).append(e)
    return out


def lookup(db, key, section="properties"):
    """Entries whose id is `key` (int, '0x..', 'key_..' or a name to hash).  Eight bare
    hex digits are read as a hash first; when no entry has that id they are hashed as a
    name (a name can consist of eight hex digits)."""
    table = by_hash(db, section)
    if isinstance(key, str):
        s = key.lower()
        bare = True
        for pre in ("key_", "0x"):
            if s.startswith(pre):
                s, bare = s[len(pre) :], False
        named = kapow_props.name_hash(key.split(":", 1)[0])
        try:
            if len(s) != 8:
                raise ValueError(s)
            key = int(s, 16)
        except ValueError:
            key = named
        else:
            if bare and key not in table:
                key = named
    return table.get(key, [])


def compare_names(db, table=None):
    """Database property names against a {hash: spelling} table (default: the
    toolkit's `kapow_props.namedict()`).  Lists are sorted by hash."""
    if table is None:
        table = kapow_props.namedict()
    res = {"agree": [], "case_only": [], "different": [], "missing_in_table": []}
    seen = set()
    for h, ents in sorted(by_hash(db).items()):
        seen.add(h)
        names = sorted({e["name"] for e in ents})
        have = table.get(h)
        row = {"hash": "%08x" % h, "database": names, "table": have}
        if have is None:
            res["missing_in_table"].append(row)
        elif have in names:
            res["agree"].append(row)
        elif have.lower() in {n.lower() for n in names}:
            res["case_only"].append(row)
        else:
            res["different"].append(row)
    res["table_only"] = [
        {"hash": "%08x" % h, "table": n} for h, n in sorted(table.items()) if h not in seen
    ]
    res["counts"] = {k: len(v) for k, v in res.items() if isinstance(v, list)}
    return res


def dump_json(db, path):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(db, fh, indent=1)
        fh.write("\n")


def main(argv=None):
    """`script_database.py DATABASE.bin [OUT.json] [--find KEY ...]`"""
    argv = list(sys.argv[1:] if argv is None else argv)
    finds = []
    while "--find" in argv:
        i = argv.index("--find")
        if i + 1 >= len(argv):
            print("--find needs a hash or a name", file=sys.stderr)
            return 2
        j = i + 1
        while j < len(argv) and not argv[j].startswith("--"):
            finds.append(argv[j])
            j += 1
        del argv[i:j]
    if not argv or argv[0] in ("-h", "--help"):
        print(main.__doc__)
        return 0 if argv else 2
    try:
        db = load(argv[0])
    except (OSError, DatabaseError) as ex:
        print("error: %s" % ex, file=sys.stderr)
        return 1
    print(
        "%s: %d properties, %d messages, %s-endian, %d of %d bytes%s"
        % (
            argv[0],
            db["property_count"],
            db["message_count"],
            db["byte_order"],
            db["consumed"],
            db["size"],
            "" if db["exact"] else "  (NOT consumed exactly)",
        )
    )
    for typ, n in type_histogram(db).items():
        print("  %-28s %d" % (typ, n))
    for key in finds:
        hits = lookup(db, key) + lookup(db, key, "messages")
        if not hits:
            print("  %s: not in the database" % key)
        for e in hits:
            print("  %s: %s  %s" % (key, e["hash"], e.get("text") or "%(name)s:%(type)s" % e))
    if len(argv) > 1:
        dump_json(db, argv[1])
        print("wrote %s" % argv[1])
    return 0 if db["exact"] else 1


if __name__ == "__main__":
    sys.exit(main())
