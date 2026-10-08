"""canonical_names -- one spelling for paths whose letter case differs between archives.

Each archive stores an asset path in the letter case of its own build, and the
engine resolves names without regard to it (name_hash folds every byte with
& 0xDF; the string compare 0x42536e accepts bytes that differ only in bit 0x20).
The same asset therefore has two spellings across the six game sets, and inside
one archive a reference can be spelled differently from the asset it names.

Two modes, `--names canonical|stored` on the command line or $WATCHMEN_NAMES:

  "canonical" (default)  every output path and every name the toolkit derives
              from one is spelled as `canonical_names.json` lists it; a path the
              table does not list keeps the archive's spelling.  A folder is
              spelled once per export: as the table lists it, else as the first
              asset written into it spells it, and extracted/, textures/,
              models/ and audio/ all use that spelling (share_folders).  The
              files `extract` brings from beside a loose-folder source are
              named in lower case, as an archive names them.  The tables written
              from an export (level JSON, particle index, fx / anim / sound /
              grade tables) spell every string that names an exported file as
              the file is written and keep the string the game stores beside it
              under "stored" (ExportIndex, respell_export).
  "stored"    the archive's spelling everywhere, as before.

The table is keyed by the folded path up to and including one component, so it
names folders and files alike:

    "art/props/common/chains": "chains"
    "art/props/common/garbage/textures/garbagepile_01.bmp": "GarbagePile_01.bmp"

A Run collects what one `extract` respelled and writes `_canonical_names.json`
into the output folder: canonical name -> the spelling(s) the archive stores.

Decoded asset data keeps the strings of the asset: every JSON under extracted/
(.fragment.json with its nodes_full, .sequence.json, .terrain.json, ...), the
per-file particle JSON, `config` / `config_tree` of a nav JSON and the sheet
properties of sheet.json.  The engine reads those strings without regard to
letter case; resolve(export_dir, string) gives the file one names.
"""

import json
import os
import re

ENV = "WATCHMEN_NAMES"
MODES = ("canonical", "stored")
DEFAULT_MODE = "canonical"
FORMAT = "watchmen-canonical-names/1"
#: the per-export record `extract` writes into its output folder
RUN_FILE = "_canonical_names.json"
RUN_FORMAT = "watchmen-export-names/1"
#: key of the archive's spelling in a texture's sheet.json and a model's .model.json
STORED_KEY = "stored_name"

_HERE = os.path.dirname(os.path.abspath(__file__))
_TABLE = None
#: the Run of the `extract` in progress (None outside one): references resolve
#: to the spelling its assets were written under
CURRENT = None
#: key of the strings the game stores, beside the respelled fields of a record
#: of a table written from an export: {field: the value as stored}
REF_STORED_KEY = "stored"
#: the output trees of one export whose paths are asset names: one folder
#: spelling for all of them (share_folders)
SHARED_TREES = ("extracted", "textures", "models", "audio")
#: the trees a string of a table can name a file in (ExportIndex)
REF_TREES = ("extracted", "textures", "models", "audio", "files/data", "files")
#: (output tree or shared group, folded folder path) ->
#: [spelling written, other spellings seen, the trees that wrote into it]
_FOLDERS = {}
#: output tree -> the group it shares its folder spellings with (share_folders)
_GROUPS = {}


def mode(value=None):
    """The naming in force: `value`, else $WATCHMEN_NAMES, else "canonical"."""
    v = value or os.environ.get(ENV) or DEFAULT_MODE
    if v not in MODES:
        raise ValueError("names must be one of %s, not %r" % (", ".join(MODES), v))
    return v


def is_canonical(value=None):
    return mode(value) == "canonical"


def fold(text):
    """ASCII letters to lower case, nothing else: the letters the engine's name
    hash and compare do not tell apart."""
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in str(text))


def table():
    """{folded path: spelling of its last component} from canonical_names.json."""
    global _TABLE
    if _TABLE is None:
        with open(os.path.join(_HERE, "canonical_names.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        if doc.get("format") != FORMAT:
            raise ValueError(
                "canonical_names.json: format %r, not %r" % (doc.get("format"), FORMAT)
            )
        _TABLE = dict(doc["names"])
    return _TABLE


def _parts(path):
    return [p for p in str(path).replace("\\", "/").split("/") if p]


def canonical_parts(parts):
    """Path components -> the same components in the table's spelling."""
    names = table()
    out, key = [], ""
    for part in parts:
        key = key + "/" + fold(part) if key else fold(part)
        out.append(names.get(key, part))
    return out


def key(path):
    """The folded form of a path: '/'-separated, no leading slash."""
    return "/".join(fold(p) for p in _parts(path))


def canonical(path, value=None):
    """An asset or archive path in its canonical spelling.

    In "stored" mode, and for a path no table entry (and no asset of the
    `extract` in progress) covers, the string comes back unchanged.  A respelled
    path keeps its leading slash and is '/'-separated."""
    if not path or not is_canonical(value):
        return path
    text = str(path)
    parts = _parts(text)
    if CURRENT is not None:
        written = CURRENT.written.get("/".join(fold(p) for p in parts))
        if written is not None:
            new = _parts(written)
            return text if new == parts else _join(text, new)
    new = canonical_parts(parts)
    return text if new == parts else _join(text, new)


def archive_name(name, value=None):
    """A file taken from beside a loose-folder source under the name an archive
    gives it: lower case (no entry name of the four archives holds an upper-case
    letter; the loose Part 1 folders spell data/Levels/Game_Levels/<Level>/
    Gameplay).  "stored" mode: unchanged."""
    return fold(name) if name and is_canonical(value) else name


def _join(text, parts):
    lead = "/" if text[:1] in "/\\" else ""
    return lead + "/".join(parts)


def share_folders(root, trees=SHARED_TREES):
    """The output trees `trees` below the export folder `root` spell their folders
    alike from here on: a folder takes the table's spelling, else that of the
    first path any of the trees writes into it.  `extract` writes every asset to
    extracted/ before it decodes it, so that is the spelling of extracted/."""
    root = os.path.abspath(str(root))
    for tree in trees:
        _GROUPS[os.path.join(root, tree)] = ("shared", root)


def output_parts(base, parts, value=None):
    """The components of one output path below the tree `base`: the table's
    spelling, and for every folder the spelling of the first path that named it
    in this process -- in `base`, or in any tree it shares its folders with
    (share_folders) -- so a case-sensitive file system gets the one folder a
    case-insensitive one makes, and the trees of an export agree folder for
    folder.  The last component (the file) is only looked up in the table.
    "stored" mode: `parts` unchanged."""
    if not parts or not is_canonical(value):
        return list(parts)
    parts = canonical_parts(parts)
    tree = os.path.abspath(str(base))
    group = _GROUPS.get(tree, tree)
    out, folded = [], ""
    for part in parts[:-1]:
        folded = folded + "/" + fold(part) if folded else fold(part)
        seen = _FOLDERS.setdefault((group, folded), [part, set(), set()])
        if seen[0] != part:
            seen[1].add(part)
        seen[2].add(tree)
        out.append(seen[0])
    return out + [parts[-1]]


def folder_spellings(root):
    """{output-relative folder as written: [other spellings its assets store]}
    for the folders below `root` that output_parts() respelled, one entry per
    output tree that holds the folder."""
    root = os.path.abspath(str(root))
    out = {}
    for (group, folded), (first, others, trees) in _FOLDERS.items():
        if not others:
            continue
        # the folder as written: every level takes its own first spelling
        levels, acc = [], ""
        for comp in folded.split("/"):
            acc = acc + "/" + comp if acc else comp
            levels.append(_FOLDERS[(group, acc)][0])
        for tree in sorted(trees):
            try:
                inside = os.path.commonpath([root, tree]) == root
            except ValueError:  # another drive
                inside = False
            if not inside:
                continue
            rel = os.path.relpath(tree, root).replace(os.sep, "/")
            out["/".join(([] if rel == "." else [rel]) + levels)] = sorted(others)
    return dict(sorted(out.items()))


def written_parts(base, parts):
    """`parts` as output_parts() spelled them for a path already written below
    `base`: the folders in the spelling on record, nothing new noted."""
    tree = os.path.abspath(str(base))
    group = _GROUPS.get(tree, tree)
    out, folded = [], ""
    for part in parts[:-1]:
        folded = folded + "/" + fold(part) if folded else fold(part)
        seen = _FOLDERS.get((group, folded))
        out.append(seen[0] if seen else part)
    return out + list(parts[-1:])


class Run:
    """What one `extract` respelled.

    name(stored)       -> the name to write under; remembers canonical -> stored
    renamed_as(written, stored)   the same note, made by the caller
    archive_name(stored)  the same for a file from beside a loose folder
    wrote(name)        an asset was written under `name`: references to it in
                       another letter case resolve to this spelling (canonical())
    stored_of(name)    the archive's spelling of a respelled name, else None
    document() / write(out_dir)   the `_canonical_names.json` record"""

    def __init__(self, value=None):
        self.mode = mode(value)
        self.renamed = {}  # canonical name -> [stored spellings]
        self.twins = {}  # written name -> [further stored spellings]
        self.written = {}  # folded name -> name written

    def name(self, stored, record=True):
        """The table's spelling of an asset or archive path (this IS the asset,
        not a reference: what the run wrote before plays no part).  `record`
        False leaves the bookkeeping to the caller (renamed())."""
        if self.mode != "canonical" or not stored:
            return stored
        parts = _parts(stored)
        new = canonical_parts(parts)
        if new == parts:
            return stored
        new = _join(str(stored), new)
        if record:
            self.renamed_as(new, stored)
        return new

    def renamed_as(self, written, stored):
        """`stored` was written as `written` (nothing is noted when they are equal)."""
        if written != stored:
            known = self.renamed.setdefault(written, [])
            if stored not in known:
                known.append(stored)

    def archive_name(self, stored):
        """archive_name(), remembered like name()."""
        new = archive_name(stored, self.mode)
        self.renamed_as(new, stored)
        return new

    def wrote(self, name):
        if self.mode == "canonical":
            self.written.setdefault(key(name), name)

    def twin(self, stored, written):
        known = self.twins.setdefault(written, [])
        if stored not in known:
            known.append(stored)

    def stored_of(self, name):
        known = self.renamed.get(name)
        return known[0] if known else None

    def document(self, out_dir=None):
        doc = {
            "format": RUN_FORMAT,
            "names": self.mode,
            "note": (
                "renamed: output name -> the spelling the archive stores, for every asset "
                "written under the canonical spelling of wlib/canonical_names.json and "
                "every file brought from beside a loose folder (lower case).  twins: "
                "output name -> further spellings the same asset has in other blocks of "
                "this archive (written once).  Both name the asset as its path is written "
                "below extracted/, textures/, models/ and audio/, which spell every folder "
                "alike.  folders: output folder -> other spellings of its last component "
                "among the paths written into it.  With --names stored nothing is renamed "
                "and folders are not tracked."
            ),
            "renamed": {k: list(v) for k, v in sorted(_as_written(self.renamed, out_dir))},
            "twins": {k: sorted(v) for k, v in sorted(_as_written(self.twins, out_dir))},
            "folders": folder_spellings(out_dir) if out_dir and self.mode == "canonical" else {},
        }
        return doc

    def write(self, out_dir):
        path = os.path.join(str(out_dir), RUN_FILE)
        os.makedirs(str(out_dir), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(self.document(out_dir), indent=1) + "\n")
        return path


def _as_written(names, out_dir):
    """[(name with its folders as the export spells them, value)] of a Run table."""
    if not out_dir:
        return list(names.items())
    base = os.path.join(str(out_dir), SHARED_TREES[0])
    out = []
    for name, v in names.items():
        parts = _parts(name)
        new = written_parts(base, parts)
        out.append((name if new == parts else _join(str(name), new), v))
    return out


def begin(value=None):
    """Start the Run of an `extract`; canonical() follows it until end()."""
    global CURRENT
    CURRENT = Run(value)
    return CURRENT


def end():
    global CURRENT
    CURRENT = None


# ---------------------------------------------------------------------------
# References: the strings of a table that name a file of the export
# ---------------------------------------------------------------------------
#: file-name endings `extract` adds to an asset name, per output tree
_ADDED = {
    "models": (".model.json", ".obj", ".mtl", ".glb"),
    "audio": (".ogg", ".wav", ".mp3", ".xma", ".json"),
}
#: the tree an asset of this ending is looked up in first
_FIRST_TREE = {".bmp": "textures", ".tga": "textures", ".model": "models"}
_SEPARATORS = ",;|"
_SPLIT = re.compile("([%s])" % re.escape(_SEPARATORS))


def export_mode(export_dir=None, value=None):
    """The naming the tables of an export follow: `value`, else $WATCHMEN_NAMES,
    else what the export's own `_canonical_names.json` says, else "canonical"."""
    v = value or os.environ.get(ENV)
    if not v and export_dir:
        try:
            with open(os.path.join(str(export_dir), RUN_FILE), encoding="utf-8") as fh:
                v = json.load(fh).get("names")
        except (OSError, ValueError, AttributeError):
            v = None
    return mode(v if v in MODES else None)


class ExportIndex:
    """The asset paths of an `extract` output folder as its files spell them.

    spell(string)   a string that names an exported file, in the letter case of
                    that file ('/'-separated, a leading slash kept); any other
                    string unchanged.  A string of several paths separated by
                    , ; or | is respelled path by path.
    find(string)    (tree, path below the tree as written) or None

    An asset is looked up by its folded path: a texture is the folder
    textures/<path>, a model the files models/<path>.obj / .glb, anything else
    the file below extracted/, audio/, files/data/ or files/ (a loose file of the
    game folder is named by the game without the leading data/: the movie
    /Art/cutscenes/Cutscene10A.bik is files/data/art/cutscenes/cutscene10a.bik).
    When the trees of an export
    spell a folder differently (an export made before they shared one spelling),
    a .bmp / .tga follows textures/ and a .model follows models/."""

    def __init__(self, export_dir, trees=REF_TREES):
        self.root = str(export_dir)
        self.trees = {}
        for tree in trees:
            names = self.trees[tree] = {}
            top = os.path.join(self.root, tree)
            if not os.path.isdir(top):
                continue
            added = _ADDED.get(tree, ())
            for where, dirs, files in os.walk(top):
                dirs.sort()
                rel = os.path.relpath(where, top).replace(os.sep, "/")
                rel = "" if rel == "." else rel
                if tree == "textures":  # a texture is a folder of layer images
                    if rel and files:
                        names.setdefault(fold(rel), rel)
                    continue
                for f in sorted(files):
                    path = rel + "/" + f if rel else f
                    names.setdefault(fold(path), path)
                    low = fold(f)
                    for end in added:
                        if low.endswith(end) and len(f) > len(end):
                            asset = path[: -len(end)]
                            names.setdefault(fold(asset), asset)
                            break

    def find(self, ref):
        if not isinstance(ref, str) or not ref or len(ref) > 1024:
            return None
        parts = _parts(ref)
        if len(parts) < 2 or "." not in parts[-1]:
            return None
        folded = "/".join(fold(p) for p in parts)
        first = _FIRST_TREE.get(os.path.splitext(folded)[1])
        order = ([first] if first in self.trees else []) + [t for t in self.trees if t != first]
        for tree in order:
            hit = self.trees[tree].get(folded)
            if hit is not None:
                return tree, hit
        return None

    def spell(self, ref):
        if not isinstance(ref, str) or "/" not in ref.replace("\\", "/"):
            return ref
        hit = self.find(ref)
        if hit is not None:
            new = hit[1].split("/")
            return ref if new == _parts(ref) else _join(ref, new)
        if any(sep in ref for sep in _SEPARATORS):
            tokens = _SPLIT.split(ref)  # the separators stay, at the odd positions
            new = [t if i % 2 else self._token(t) for i, t in enumerate(tokens)]
            if new != tokens:
                return "".join(new)
        return ref

    def _token(self, token):
        """One path of a separated list, its surrounding blanks kept."""
        core = token.strip()
        hit = self.find(core) if core else None
        if hit is None:
            return token
        new = hit[1].split("/")
        if new == _parts(core):
            return token
        lead = token[: len(token) - len(token.lstrip())]
        return lead + _join(core, new) + token[len(token.rstrip()) :]


def resolve(export_dir, ref, index=None):
    """The file or folder of an export a stored asset string names, as a path
    relative to the export folder ("textures/art/.../Fire_01.BMP"), or None.
    The lookup ignores letter case, as the engine does; pass an ExportIndex to
    resolve many strings."""
    hit = (index or ExportIndex(export_dir)).find(ref)
    return hit[0] + "/" + hit[1] if hit else None


def respell(doc, index, skip=(REF_STORED_KEY, STORED_KEY)):
    """Respell, in place, every string of the JSON document `doc` that names a
    file of the export (ExportIndex.spell) -> the number of strings changed.

    The string as stored is kept in the record that holds the field, under
    "stored": {field: value as stored} -- for a list the list as stored (for a
    list that also holds records: {position: string}), for a map whose keys are
    respelled {key written: key stored}.  Fields named "stored" or "stored_name"
    are left alone, so a second pass changes nothing; a record that has a
    "stored" value of its own that is not such a map keeps its strings."""
    count = [0]

    def strings(v):
        """A string, or a list of strings and lists, respelled; records in a list
        are walked in place."""
        if isinstance(v, str):
            new = index.spell(v)
            if new != v:
                count[0] += 1
            return new
        if isinstance(v, list):
            return [strings(x) for x in v]
        if isinstance(v, dict):
            walk(v)
        return v

    def note(rec, field, value):
        known = rec.get(REF_STORED_KEY)
        if not isinstance(known, dict):
            known = rec[REF_STORED_KEY] = {}
        known.setdefault(field, value)

    def records(v):
        """The records inside a value, walked; the value's own strings left alone."""
        if isinstance(v, dict):
            walk(v)
        elif isinstance(v, list):
            for x in v:
                records(x)

    def walk(rec):
        # a record with a "stored" value of its own (not ours) keeps its strings
        own = REF_STORED_KEY in rec and not isinstance(rec[REF_STORED_KEY], dict)
        for field in [k for k in rec if k not in skip and k != NAMES_KEY]:
            v = rec[field]
            if own:
                records(v)
            elif isinstance(v, str):
                new = strings(v)
                if new != v:
                    rec[field] = new
                    note(rec, field, v)
            elif isinstance(v, list):
                new = strings(v)
                if new != v:
                    rec[field] = new
                    if all(isinstance(x, (str, list)) for x in v):
                        note(rec, field, v)
                    else:
                        note(
                            rec,
                            field,
                            {str(i): x for i, x in enumerate(v) if new[i] != x},
                        )
            elif isinstance(v, dict):
                renamed = {}
                for k in v:
                    new = index.spell(k) if isinstance(k, str) else k
                    if new != k and new not in v and new not in renamed.values():
                        renamed[k] = new
                if renamed:
                    count[0] += len(renamed)
                    items = [(renamed.get(k, k), x) for k, x in v.items()]
                    v.clear()
                    v.update(items)
                    note(rec, field, {new: k for k, new in renamed.items()})
                walk(v)

    if isinstance(doc, dict):
        walk(doc)
    elif isinstance(doc, list):
        strings(doc)
    return count[0]


def respell_after(doc, index, field, prefix):
    """Respell, in place, the path that follows `prefix` in every string field
    `field` of the JSON document `doc` ("label": "MOVIE /Art/cutscenes/X.bik")
    -> the number of strings changed.  The text as stored goes under "stored"
    of the record, as respell() does it."""
    count = 0
    todo = [doc]
    while todo:
        v = todo.pop()
        if isinstance(v, list):
            todo.extend(v)
        elif isinstance(v, dict):
            todo.extend(x for k, x in v.items() if k not in (REF_STORED_KEY, NAMES_KEY))
            text = v.get(field)
            known = v.get(REF_STORED_KEY)
            if not isinstance(text, str) or not text.startswith(prefix):
                continue
            if REF_STORED_KEY in v and not isinstance(known, dict):
                continue  # a "stored" value of its own: the record keeps its strings
            new = prefix + index.spell(text[len(prefix) :])
            if new != text:
                v[field] = new
                if not isinstance(known, dict):
                    known = v[REF_STORED_KEY] = {}
                known.setdefault(field, text)
                count += 1
    return count


#: what a table says about the spelling of its strings (key NAMES_KEY)
NAMES_KEY = "asset_names"
_NAMES_NOTE = (
    "A string that names a file of this export is spelled as that file is written "
    "(textures/<path>/ for a texture, models/<path>.obj and .glb for a model, else the "
    "file below extracted/, audio/, files/data/ or files/), so it finds the file on a "
    "case-sensitive file system.  Where that differs from the string the game stores, the record holds "
    'the stored one under "stored": {field: value as stored}.  --names stored: every '
    "string as the game stores it."
)


def respell_export(doc, export_dir, index=None, value=None):
    """respell() for a table written from the export `export_dir`, when its naming
    (export_mode) is "canonical"; the table gets an "asset_names" entry that says
    which spelling it holds and how many strings were respelled.  `doc` is
    changed in place and returned ("stored": returned as it is)."""
    if not isinstance(doc, dict) or not export_dir:
        return doc
    if export_mode(export_dir, value) != "canonical":
        return doc
    done = doc.get(NAMES_KEY)
    n = respell(doc, index or ExportIndex(export_dir))
    if isinstance(done, dict) and done.get("spelling") == "export":
        n += done.get("respelled", 0)
    doc[NAMES_KEY] = {"spelling": "export", "respelled": n, "note": _NAMES_NOTE}
    return doc
