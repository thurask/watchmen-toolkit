#!/usr/bin/env python3
"""watchmen — CLI for the Watchmen: The End Is Nigh asset-extraction toolkit
(Parts 1 & 2; PC, Xbox 360, PS3).

The master-script functionality without the spaghetti. All real logic lives in
wlib/ (see watchmenlib.py facade); this is just the CLI.

Commands
--------
  all NAZ OUT                    EVERYTHING in order: extract -> binds -> character glbs
  extract NAZ OUT [opts]         Full asset extraction (+JSON for all types)
                                 opts passed through, e.g. --vgmstream-cli PATH
                                 (any platform's vgmstream-cli; decodes console
                                 X360 XMA2 / PS3 MP3 audio to .wav — without it
                                 console audio is written as .xma/.mp3)
  binds NAZ OUT_DIR              Build engine-exact FILE-ONLY binds for all skeletons
  charlibs EXTRACT_OUT OUT_DIR   Textured+animated character-library glbs (needs extract+binds)
  faces EXTRACT_OUT OUT_DIR      Cutscene-head glbs: engine-exact face binds + the 24
                                 facial expression POSES (game has no keyframed face anims)
  characters EXTRACT_OUT OUT_DIR [NAZ]  Folder per character, one glb per fragment
                                 variant, EVERY animation of its skeleton (resumable)
  fragment FILE [OUT.json]       Lossless .fragment -> JSON
  bake CLIPNAME BIND OUT.npy     Engine-exact palettes for one clip
  char FRAG.json VARIANT OUT.glb Character variant -> GLB with all its clips
  hash NAME                      Kapow property-key hash of a name
  gendata SUBCMD ...             Regenerate wlib's data tables from a game
                                 install (strings/regdump/propnames/keys-export/
                                 keys-import/check; see gendata -h)

Examples
--------
  python3 watchmen.py all game.naz OUT      # fresh install -> everything
  python3 watchmen.py extract game.naz OUT
  python3 watchmen.py fragment OUT/extracted/.../Gimp.fragment
  python3 watchmen.py char Gimp.fragment.json Gimp2 CHAR_Gimp2.glb
"""

import os, sys, json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "wlib"))
_ARGV = list(sys.argv)  # watchmenlib rewrites sys.argv for bake_v4
import watchmenlib as wl

# per-command positional spec: (min_positional_args, one-line usage).
# lets a bare/short `watchmen.py CMD` print a clean usage line instead of an
# IndexError traceback, and gives every command its own -h/--help.
USAGE = {
    "all": (2, "all NAZ OUT"),
    "extract": (2, "extract NAZ OUT [--vgmstream-cli PATH] [--keep-xma] [--glb ...]"),
    "binds": (2, "binds NAZ OUT_DIR"),
    "charlibs": (2, "charlibs EXTRACT_OUT OUT_DIR [NAZ]"),
    "faces": (2, "faces EXTRACT_OUT OUT_DIR"),
    "characters": (2, "characters EXTRACT_OUT OUT_DIR [NAZ]"),
    "fragment": (1, "fragment FILE [OUT.json]"),
    "bake": (3, "bake CLIPNAME BIND OUT.npy"),
    "char": (3, "char FRAG.json VARIANT OUT.glb"),
    "hash": (1, "hash NAME"),
    "gendata": (1, "gendata strings|regdump|propnames|keys-export|keys-import|check ..."),
}


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return 0 if len(argv) >= 2 else 1
    cmd, args = argv[1], argv[2:]
    if cmd not in USAGE:
        print("unknown command %r" % cmd)
        print(__doc__)
        return 1
    if "-h" in args or "--help" in args:
        if cmd == "extract":
            # forward to the extractor's argparse help (shows --vgmstream-cli, --glb, ...)
            import watchmen_extract as _we

            return _we.main(["--help"])
        print("usage: watchmen.py %s" % USAGE[cmd][1])
        return 0
    need = USAGE[cmd][0]
    if len(args) < need:
        print("usage: watchmen.py %s" % USAGE[cmd][1])
        print("  (%s takes at least %d argument%s)" % (cmd, need, "" if need == 1 else "s"))
        return 2

    if cmd == "extract":
        naz, out = args[0], args[1]
        wl.extract_all(naz, out, *args[2:])  # extras: e.g. --vgmstream-cli PATH

    elif cmd == "all":
        naz, out = args[0], args[1]
        print("[1/3] extract %s -> %s" % (naz, out))
        wl.extract_all(naz, out, *args[2:])
        # binds + character glbs work on console too (2026-07-15): the
        # skeleton/mesh/skin decoders are byte-order aware (X360/PS3 = BE).
        print("[2/3] binds -> %s/binds" % out)
        binds = wl.ensure_binds(naz, os.path.join(out, "binds"), extract_dir=out)
        print("[3/3] character glbs -> %s/characters" % out)
        import char_lib

        char_lib.build_all(out, binds, os.path.join(out, "characters"))
        print("done.")

    elif cmd == "characters":
        exout, outdir = args[0], args[1]
        naz = args[2] if len(args) > 2 else "game.naz"
        import characters_export

        pending = characters_export.export(exout, outdir, naz)
        pending = pending if isinstance(pending, int) else len(pending or ())
        print(
            "pending bakes: %d%s"
            % (pending, " -- rerun to continue" if pending else " -- complete")
        )

    elif cmd == "faces":
        import face_export

        face_export.export(args[0], args[1])

    elif cmd == "charlibs":
        exout, outdir = args[0], args[1]
        binds = wl.ensure_binds(
            args[2] if len(args) > 2 else "game.naz",
            os.path.join(exout, "binds"),
            extract_dir=exout,
        )
        import char_lib

        char_lib.build_all(exout, binds, outdir)

    elif cmd == "binds":
        naz, out = args[0], args[1]
        r = wl.ensure_binds(naz, out)
        for k, v in sorted(r.items()):
            print("%-8s %s" % (k, v))

    elif cmd == "fragment":
        j = wl.fragment_json_file(args[0])
        out = args[1] if len(args) > 1 else args[0] + ".json"
        open(out, "w").write(json.dumps(j, indent=1))
        print("wrote", out, "(lossless:", j.get("lossless"), ")")

    elif cmd == "bake":
        clip, bind, out = args[0], args[1], args[2]
        import numpy as np

        pal, dur = wl.bake(clip, bind)
        np.save(out, pal)
        print("baked %s %s dur %.2fs -> %s" % (clip, pal.shape, dur, out))

    elif cmd == "char":
        frag, variant, out = args[0], args[1], args[2]
        wl.build_variant_glb(frag, variant, out)

    elif cmd == "hash":
        print("%08x" % wl.kapow_hash(args[0]))

    elif cmd == "gendata":
        import gen_data

        return gen_data.main(["gen_data"] + args)

    else:
        print("unknown command %r" % cmd)
        print(__doc__)
        return 1
    return 0


def cli():
    """Console-script entry point (``watchmen`` after ``pip install``)."""
    sys.exit(main(_ARGV))


if __name__ == "__main__":
    cli()
