# Changelog

## 1.1.0 — 2026-07-24

A correctness pass over the whole toolkit. **Three changes alter output**; the
rest are robustness, security, portability and packaging. Re-export anything you
generated with 1.0.0.

### Output-affecting

- **Axis convention.** The Kapow engine is Y-up, the same as glTF, so no axis
  conversion is applied any more. Previously both GLB writers rotated positions
  by a Z-up→Y-up matrix. In `variant_glb` an exact inverse was folded into the
  joint world matrices, so the animated result cancelled out correctly but the
  raw `POSITION` data — and therefore the bind pose — was 90° about X. In
  `rig_glb` nothing cancelled it, so every model it wrote (static props, heads,
  and rigged bodies) came out on its back. Animated character output is
  numerically unchanged (verified 1e-7 against the previous writer); `POSITION`
  and everything `rig_glb` produces is now upright.

  Evidence: skinned frame-0 bbox of a shipped character GLB is 1.75 m tall along
  Y with feet down, while its `POSITION` alone measured 1.80 m along Z. The
  original Z-up reading came from `decode_skeleton_model.py` (see below), which
  was superseded for an off-by-one bug and also reported a 1.4 m character.

- **Character GLB rest pose.** Joint nodes were emitted with identity TRS while
  the inverse bind matrices were real, so with no animation playing the skinning
  matrix was the IBM alone and the mesh rendered in bind-*local* space —
  measured 0.72 m mean vertex displacement and a mesh collapsed to about a fifth
  of its animated size. Joint nodes now carry the bind pose. Anything that shows
  the scene before you pick an action (Blender's rest pose, the default glTF
  viewer state, thumbnailers) is now correct.

- **Clip timing in `variant_glb.build()`** (i.e. `watchmen char` and
  `wl.build_variant_glb`). It read the clip header's field 0 as the duration;
  field 0 is the key RATE and field 1 is the duration. Since
  `keyRate == (keyCount-1)/duration`, the computed fps came out as
  approximately the duration in seconds — roughly 3× too slow on a typical
  clip. `bake_v4` had been fixed for this in 2026-07-09 and carries a comment
  saying so 20 lines above the offending call; `build()` was never updated. The
  bulk paths (`watchmen characters`, `charlibs`) computed fps correctly via
  `bake_v4.fps_for` and are unaffected.

### Correctness

- `OUT/skeletons/*.json` was built by `decode_skeleton_model.decode()`, which
  that module's own docstring marked SUPERSEDED for an off-by-one: the 28-byte
  `[pos][quat]` transform *precedes* the name in a node record, so every bone
  was published carrying its successor's rest transform, the last bone of every
  skeleton was dropped, `bone_count` was short by one, and parents were guessed
  from biped names instead of read from the record. `extract_skeletons` is now
  built on `parse_model_nodes.parse()`, and `decode_skeleton_model.py` is
  **removed**.
- Console (X360/PS3) skeletons: `extract_skeletons` read the per-node parent
  field little-endian only, which threw `struct.error` on every big-endian
  header — swallowed by two `except Exception: pass` handlers, so console runs
  logged "0 base skeletons decoded" and every rigged console GLB got joints
  named `bone_0`, `bone_1`, … `_model_is_body` had the same problem but returned
  empty instead of raising, so its safety net never fired and every skinned
  console character was exported *static*, silently. Both now use the same
  byte-order autodetection as the rest of the codebase.
- `kapow_json`: the duplicate-resource-reference filter was `pass` where
  `continue` was meant, so every fragment JSON emitted each resource path twice,
  usually under two different key names.
- `parse_model_nodes`: bounds-check every record read, and fail loudly when the
  number of nodes parsed disagrees with the header's own count (a silently
  dropped node shifted every later parent index and corrupted the hierarchy).
- `jiggle_d6`: solver softening used a hardcoded 120 Hz instead of the
  integration rate read from the fragment. No change at the shipped 60 Hz;
  correct, and stable, at any other rate.
- glTF conformance: empty `animations`/`skins`/`images`/`textures`/`materials`
  arrays are no longer emitted (glTF 2.0 sets `minItems: 1`; the Khronos
  validator reports them as errors), and animation input accessors carry their
  real `min`/`max` instead of a hardcoded `0.0`.

### Security / robustness

- `safe()` neutralizes Windows drive-relative entry names (`C:/…`, `D:evil.txt`,
  which `pathlib` treats as a new anchor and which therefore escaped the output
  directory), maps an empty entry name to `_unnamed` instead of returning the
  output directory itself, and asserts containment.
- Removed a `pickle.load` fallback to `/tmp/prop_hash_dict.pkl` — a
  world-writable path, and `pickle.load` executes code. A missing or corrupt
  table now warns on stderr instead of silently degrading every property key to
  a hex hash behind a bare `except:`.
- `decode_sequence` bounds-checks truncated buffers and has a forward-progress
  guard (its resync window scans backwards, so a 2-cycle was representable).
- `naz_entries` on a file shorter than the EOCD record says "not a NAZ archive"
  instead of raising `OSError(EINVAL)` from a negative seek.
- A stale `<clip>.npz.tmp.npz` from a killed chunked bake matched the resume
  glob and was loaded as a real animation — permanently, since nothing cleaned
  it up. Temps are now skipped and swept.

### Determinism and portability

- `build_texture_index` and the loose-tree walk no longer depend on filesystem
  enumeration order, so which texture directory wins for a colliding basename is
  stable across machines.
- All text output is written UTF-8 with LF line endings, so output is
  byte-identical across platforms.

### Library surface

- `import watchmenlib` no longer rewrites the host program's `sys.argv`, no
  longer raises the process recursion limit, and no longer resolves paths into
  `site-packages`. `bake_v4.bake()` takes `bind=` / `conj=` / `bank=` directly;
  the six `sys.argv = [...]` + `importlib.reload()` sites are gone.
- The dead `wl.BINDS` / `variant_glb.BINDS` tables (every entry pointed at a
  developer-machine directory that never shipped) are replaced by
  `wl.ensure_binds(naz, outdir)` and `variant_glb.binds_from_dir(dir)`.
  `ensure_binds` now requires an explicit `outdir` instead of defaulting to a
  path inside `site-packages` — and creating it there.
- `wlib/__init__` appends to `sys.path` instead of inserting at position 0, so
  the flat module names can no longer shadow the stdlib.

### CLI

- `watchmen --version`.
- Bad paths and wrong file types produce `error: …` lines and non-zero exit
  codes instead of tracebacks; `watchmen fragment` on an unrecognized file no
  longer writes `null` and then crashes.
- `watchmen gendata check` explains what it needs instead of tracebacking when
  there is no game install; missing positional arguments are reported.
- `watchmen --help`, `--version` and `hash` no longer import numpy, Pillow and
  three pickled data tables, and no longer fail when a data table is missing.
- `watchmen char` takes an optional `BINDDIR` and `BAKEDIR`.

### Docs and release hygiene

- Removed the author's private working-tree paths (`D:\…`, `claude/work_*/…`)
  from 12 source files and the docs, and repointed 21 references to documents
  that never shipped at the ones that do.
- Neutral phrasing around DRM: the docs no longer instruct readers to obtain a
  specific de-DRM'd executable. `gendata regdump` — the only path that needs an
  executable with an unencrypted `.text` — says so plainly and states that this
  toolkit neither provides such a binary nor helps produce one.
- `gendata regdump` sanity-checks the recovered class count, because the
  registration-function addresses it uses were reversed from one specific build.
- Added `tests/` (188 tests, no game files needed) and a `CHANGELOG`.
