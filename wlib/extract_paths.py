"""Where `extract` writes an asset: the names a run has written (`OutputNames`: a
name stored in several blocks is written once, a copy with other bytes under a
name of its own), the output name of a standalone `_h_z` / `_s_z` pair, and
archive entry names turned into paths that stay under the output folder (`safe`,
`out_rel`; the canonical spellings come from `canonical_names`).
"""

import functools
import os
import sys
from pathlib import Path

# the flat wlib modules import each other by name (`import kapow_props`); one path
# setup for this module, also when it is run as a script or loaded by file path.
# Append, never insert(0): flat module names must not shadow the stdlib.
_WLIB = os.path.dirname(os.path.abspath(__file__))
if _WLIB not in sys.path:
    sys.path.append(_WLIB)
from wutil import long_path  # noqa: E402


class OutputNames:
    """Which asset names this run has already written, so that a name stored in
    several blocks is written once and never silently overwritten.

    The level blocks repeat their shared assets (Part 2 PC: 8,711 block entries
    are 7,023 names), and the copies are byte-identical in every set measured
    (six sets: no name has two different header / stream pairs; in Part 1
    the Prison block lists 22 names without the stream its other copies have).
    place() makes the rule explicit instead of relying on that:

    * the first copy keeps the name as stored ("new");
    * a later copy with the same bytes is not written again ("repeat"); it is
      written under the FIRST copy's spelling when only the letter case differs
      (Rubble_RoofTop_02 / Rubble_Rooftop_02), which is what a case-insensitive
      file system did anyway;
    * a copy that brings the stream an earlier one lacked completes it ("fill");
    * a copy with DIFFERENT bytes gets its own name, `<stem>~<block>.<ext>`
      (`~<block>~2` ... if that is taken too), and a log line ("variant") -- the
      earlier file stays as it is.
    Blocks are processed in sorted order, so the result does not depend on the
    archive's entry order.

    `run` (a canonical_names.Run) gives every name its canonical spelling before
    it is placed and records the stored one; without it names stay as stored.

    `same_bytes` is True after place() returned "repeat" for a copy whose header
    AND stream state equal the copy already written (both with the same stream, or
    both without one); a repeat that lacks the stream the earlier copy had is
    "repeat" with same_bytes False."""

    def __init__(self, log=None, run=None):
        self._log = log if callable(log) else (lambda *a: None)
        self._run = run
        self._by = {}  # lower-case name -> [variant dict]
        self._taken = set()  # lower-case output names
        self.repeats = 0
        self.same_bytes = False
        self.case_twins = []  # (spelling skipped, spelling written)
        self.variants = []  # (name as stored, name written, block)

    @staticmethod
    def _digest(header, stream):
        import hashlib

        return (
            hashlib.sha1(header or b"").digest(),
            hashlib.sha1(stream).digest() if stream else None,
        )

    @staticmethod
    def variant_name(name, block, k=1):
        """`dir/Stem.ext` -> `dir/Stem~<block>.ext` (k > 1: `~<block>~<k>`)."""
        head, _, base = name.replace("\\", "/").rpartition("/")
        stem, dot, ext = base.partition(".")
        tag = "".join(c if c.isalnum() or c in "-_" else "_" for c in block.split("/")[-1])
        tag = tag[: -len("_block")] if tag.lower().endswith("_block") else tag
        base = "%s~%s%s%s%s" % (stem, tag or "block", "~%d" % k if k > 1 else "", dot, ext)
        return (head + "/" if _ else "") + base

    def place(self, name, block, header, stream):
        """-> (name to write under, status): "new", "repeat", "fill" or "variant"."""
        stored = name
        if self._run is not None:
            # --names canonical: the table's spelling (noted below, for the copy written)
            name = self._run.name(stored, record=False)
        key = name.replace("\\", "/").lower()
        hd, sd = self._digest(header, stream)
        known = self._by.setdefault(key, [])
        self.same_bytes = False
        for v in known:
            if v["hd"] != hd or (sd is not None and v["sd"] is not None and v["sd"] != sd):
                continue
            if stored != v["stored"] and stored not in v["twins"]:
                v["twins"].add(stored)
                if stored != v["name"]:
                    self.case_twins.append((stored, v["name"]))
                    if self._run is not None:
                        self._run.twin(stored, v["name"])
            if v["sd"] is None and sd is not None:
                v["sd"] = sd
                return v["name"], "fill"
            self.repeats += 1
            self.same_bytes = v["sd"] == sd
            return v["name"], "repeat"
        out, k = name, 1
        if known:
            out = self.variant_name(name, block)
            while out.lower() in self._taken:
                k += 1
                out = self.variant_name(name, block, k)
            self.variants.append((name, out, block))
            self._log(
                "      WARNING: %s is stored with different content in %s than in %s: written as %s"
                % (name, block, known[0]["block"], out)
            )
        self._taken.add(out.lower())
        known.append(dict(hd=hd, sd=sd, name=out, stored=stored, twins=set(), block=block))
        if self._run is not None:
            if name != stored:
                self._run.renamed_as(out, stored)
            if not known[:-1]:
                self._run.wrote(out)  # references in another letter case follow this spelling
        return out, ("variant" if known[:-1] else "new")


def standalone_output_name(names, stem, header, stream):
    """Output name of a standalone `_h_z` / `_s_z` pair (`stem` = its archive path
    without the suffix) through the run's OutputNames -> (name, status).  Two
    pairs with the same base name in different folders do not overwrite each
    other: a copy with different bytes is written as `<name>~<folder>.<ext>`
    with a WARNING, an identical one is "repeat" (not written again)."""
    stem = stem.replace("\\", "/")
    folder = stem.rpartition("/")[0]
    return names.place(stem.split("/")[-1], folder or stem, header, stream)


#: names Windows reserves for devices (in any letter case, with or without an extension)
_WIN_DEVICES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + ["COM%d" % i for i in range(1, 10)]
    + ["LPT%d" % i for i in range(1, 10)]
)


def _not_a_device(part):
    """`part`, or `_part` when Windows would open a device for it (CON, NUL.txt, ...)."""
    return "_" + part if part.split(".", 1)[0].strip().upper() in _WIN_DEVICES else part


def _no_trailing_dots(part):
    """`part` with each trailing '.' or ' ' replaced by '_': Windows drops them
    ("Foo. " opens "Foo"), so two entries could land on one file there; the same
    name is written on every system (none in the six shipped archives, measured)."""
    core = part.rstrip(". ")
    return part if core == part else core + "_" * (len(part) - len(core))


def _safe_path(base, name):
    """safe() without the Windows extended-length form."""
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    parts = [_not_a_device(_no_trailing_dots(p.replace(":", "_"))) for p in parts]
    # --names canonical (default): the table's spelling, and one spelling per folder
    parts = names_module().output_parts(base, parts)
    out = base.joinpath(*parts) if parts else base / "_unnamed"
    if os.path.commonpath([os.path.abspath(base), os.path.abspath(out)]) != os.path.abspath(base):
        raise ValueError("unsafe archive entry name %r" % name)
    return out


def safe(base, name):
    """Archive entry name -> a path guaranteed to stay under `base`.

    Entry names are attacker-controlled (rot-2 obfuscated, not authenticated), so
    strip '..'/absolute anchors AND ':' -- pathlib treats 'C:/x' as a new anchor
    on Windows and would otherwise escape `base` entirely.  A component Windows
    reserves for a device (CON, NUL.txt, ...; none in the shipped archives) gets a
    leading '_' on every platform, and so do trailing dots and spaces become '_'
    (_no_trailing_dots).  On Windows a path of LONG_PATH_LIMIT (240) characters or
    more is returned in the extended-length form \\\\?\\C:\\... (wutil.long_path), which
    opens past MAX_PATH; compare it with other paths through wutil.rel_path.

    Unless --names stored is in force the components take their canonical
    spelling (canonical_names.output_parts)."""
    return long_path(_safe_path(base, name))


def out_rel(base, name):
    """`name` as a "file" value of a JSON beside it: '/'-separated, relative to the
    output tree `base`.  With --names canonical it is the path safe() writes
    (folders in the spelling of the tree), so the value names the file on a
    case-sensitive file system too; with --names stored the name as stored."""
    if names_module().is_canonical():
        return _safe_path(Path(base), name).relative_to(Path(base)).as_posix()
    return name.replace("\\", "/").lstrip("/")


@functools.cache
def names_module():
    """canonical_names (--names canonical|stored), imported on first use."""
    import canonical_names as _cnm

    return _cnm
