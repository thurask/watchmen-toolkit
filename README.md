# watchmen-kapow-toolkit

*Disclaimer: this project was created with the help of generative AI.*

Asset-extraction toolkit for **Watchmen: The End Is Nigh, Parts 1 & 2**
(Deadline Games, 2009 — **Kapow engine**), reverse-engineered from the shipped
game files. Everything is *file-derived*: the pipeline runs on a fresh install
of the game with no captures, memory dumps, or other side data.

Supported sources, all producing identical assets (verified by 3-way audit):

| Platform | Source |
|---|---|
| PC | `game.naz` archive (or a loose `derived_pc` directory for Part 1) |
| Xbox 360 | XBLA loose `derived_x360` tree, or a `.naz` |
| PS3 | `USRDIR/.../game.naz` |

What it extracts / builds:

- **Textures** → PNG (DXT1/3/5, ATI2, L8, 32bpp; console untiling/unswizzling
  is byte-exact vs PC)
- **Models** → OBJ + rigged, textured, bind-pose **GLB** (`extract --glb`)
- **Audio** → WAV (music + SFX; console XMA2/MP3 decoded via `--vgmstream-cli`)
- **All misc formats** → lossless JSON (`.fragment`, `.pb`, `.sequence`,
  `.font`, `.particle`, `.terrain`, `.grass`, `.detailmesh`, ...) — the Kapow
  property-name hash is cracked, so every property key is named
- **Character animation** → engine-exact file-only binds for all skeletons, and
  per-character GLBs carrying *every* animation of the character's skeleton,
  including jiggle dynamics (PhysX D6 model), facial expression poses, weapon
  attachments, and the animation state machine's overlay pages

## Install

```
pip install .
```

Dependencies: `numpy`, `Pillow` (that's all). Optional external tool:
[vgmstream-cli](https://vgmstream.org) for console audio → WAV.

## Quick start

```
# everything, in order (extract -> binds -> character glbs):
watchmen all game.naz OUT

# or step by step:
watchmen extract game.naz OUT            # assets + JSON (add --glb for rigged glbs)
watchmen binds game.naz OUT/binds        # engine-exact file-only skeleton binds
watchmen characters OUT CHARS game.naz   # one glb per character variant (resumable)
watchmen faces OUT FACES                 # cutscene heads + 24 expression poses
watchmen fragment OUT/extracted/.../Gimp.fragment   # lossless fragment -> JSON
watchmen hash SomePropertyName           # Kapow property-key hash
watchmen --version
```

`watchmen --help` lists all commands; `watchmen extract --help` shows extractor
options (`--glb`, `--vgmstream-cli`, `--keep-xma`, ...).

Without installing: `python3 watchmen.py <command> ...` from this directory
works identically.

## Library use

```python
import wlib                     # puts the flat modules on sys.path
import watchmenlib as wl        # the facade — one import for everything

j = wl.fragment_json_file('X.fragment')          # lossless fragment JSON
binds = wl.ensure_binds('game.naz', 'OUT/binds') # file-only engine-exact binds
pal, dur = wl.bake('run_cycle', binds['female']) # (F,NB,3,4) engine palettes
wl.build_variant_glb('Gimp.fragment.json', 'Gimp2', 'out.glb',
                     binddir='OUT/binds')
```

(The three lines after the imports need game files; `import wlib` /
`import watchmenlib` on their own do not, and have no side effects on your
process — no `sys.argv` rewriting, no recursion-limit changes, and the package
directory is appended to `sys.path`, never prepended, so it cannot shadow the
stdlib.)

`wlib/watchmenlib.py` documents the full facade. Notable standalone modules:
`wlib/anim_state_machine.py` (animation state-machine interpreter),
`wlib/engine_schema.py` (441-class engine serialization schema recovered from
the executable), `wlib/jiggle_d6.py` (PhysX D6 jiggle integrator),
`wlib/kapow_fragment.py` (lossless `.fragment` parser, 906/906 files
round-trip).

## Tests

```
pip install -e ".[dev]"
pytest
```

The suite runs with **no game files**: it covers the archive-entry path
sanitizer, the Kapow property hash, the little/big-endian skeleton decoder
against synthetic ModelRes headers, glTF structural conformance of the GLB
writer (chunk padding, accessor alignment, accessor min/max, no empty arrays),
clip-timing arithmetic, and output determinism. It is the executable form of
the correctness claims below — if you change a decoder, this is what tells you
whether you changed its output.

Round-tripping the real corpus (the "906/906 fragments" figure) needs a game
archive and is not part of the offline suite.

## Documentation

Format specifications and the complete reverse-engineering record live in
[`docs/`](docs/INDEX.md) — start with `docs/INDEX.md`.

## Shipped data tables and their provenance

`wlib/` ships three data tables. `watchmen gendata` can regenerate them from a
game install and `gendata check GAME_ROOT` verifies the shipped copies against
a fresh regeneration:

- `prop_hash_dict.pkl` — property-hash → name dictionary. **Fully regenerable
  de novo** (`gendata strings EXE game.naz`): string harvest over the exe and
  every naz block payload + identifier tokenization. Works even on the retail
  DRM-packed `KapowMulti.exe` (its string sections are unencrypted).
- `reg_dump.json` — 441 engine classes (props, commands, defaults, UI
  captions) recovered from registration call sites in the executable's code.
  Regenerable (`gendata regdump EXE`, needs `pip install .[regdump]`) but only
  from a DRM-free executable — retail `.text` is SecuROM-encrypted in place.
  Its sibling `prop_names_from_reg.json` is a pure aggregation and is derived
  at runtime (not shipped).
- `kapow_fragment_keys.pkl` — the fragment property-key crack: names AND value
  types for ~4.5k hashes, recovered by corpus-wide type inference, caption
  synthesis, and manual work. This is research output (like the bind formula),
  not something latent in the game files — it cannot be regenerated
  mechanically. `gendata keys-export` dumps it to readable JSON for inspection
  or hand-maintenance (`keys-import` converts back).

The retired capture-fit `jiggle_params.npz` is intentionally absent: without
it the jiggle path uses the file-only PhysX D6 model, which is the promoted,
capture-parity default.

## Notes

- Skeleton binds and clip decoding are **engine-exact**: in our testing,
  validated against GPU-captured bone palettes (median joint error ~0.0000,
  rotation ≤0.5°) and against the decompiled executable's math. The captures
  themselves are research input and are not shipped, so that specific number is
  not reproducible from this repository alone; what *is* checkable here is in
  `tests/` (see **Tests** below).
- Extraction output is deterministic: repeated runs over the same archive
  produce byte-identical files, on the same platform and across platforms
  (all text output is written UTF-8 with LF endings).
- Coordinates: the Kapow engine is Y-up, the same as glTF, so no axis
  conversion is applied. GLB output is upright both at rest and animated.
- Console block payloads are big-endian; byte order is auto-detected per
  archive — there is no flag to pass.
- This toolkit reads only data you extracted from your own copy of the game;
  it ships no game assets.

## License

MIT — see [LICENSE](LICENSE). The reverse-engineered code and documentation
are original work; identifier strings inside some data tables were extracted
from the game executable for interoperability and remain their rights
holders' property (see the note in LICENSE).
