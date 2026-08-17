# Changelog

## 1.2.0 — 2026-08-17

A second correctness pass. The dominant theme: fixes the bulk `characters`
path (`char_lib`) collected in July that the single-model paths never
received. **Output-affecting for console extraction, `watchmen char`, bulk
walk/run timing, and `export_female_anims`** — details below.

### Output-affecting

- **Console rigged GLBs from the extractor.** `decode_model` auto-detected the
  byte order but didn't pass it to `decode_skin`, so the PC `stride >= 56`
  gate rejected every console (stride-44) skinned submesh and `--glb` on an
  X360/PS3 naz silently produced no skinned GLB at all. The `watchmenlib`
  facade wrapper dropped the argument too. Both now thread the order through.
- **`watchmen char` / `wl.build_variant_glb` skinning.** `variant_glb.
  load_parts` was missing the 2026-07-13 `BipNN`-prefix-insensitive bone-name
  fallback `char_lib` has, so Thug/Heavies-style name mismatches silently
  dropped mid-list bones and shifted the rotate-by-one palette (mis-skinned
  arms/head). Also ported from `char_lib`: byte-order autodetection (the path
  was little-endian-only), the `_ib_ok` clean-index-buffer guard, and
  engine-exact `submesh_materials` pairing (positional pairing textures the
  wrong submeshes when one material covers several). The extractor's OBJ/MTL
  path got the same `submesh_materials` fix.
- **Bulk locomotion timing.** `watchmen characters` never applied the
  capture-verified `SPEED_MULT` runtime sync that `watchmen char` applies, so
  the two writers disagreed on walk/run clips. The bulk path now applies it.
- **`export_female_anims`** still carried the pre-1.1.0 Z-up→Y-up conversion —
  and applied it twice (baked into POSITION *and* on the Armature root), so
  its output was rotated. No conversion is applied now; output matches the
  other writers. Also: removed an orphaned duplicate IBM accessor, replaced a
  bare `except`, and a naz without the female skeleton now fails with a clear
  message instead of a `TypeError`.
- **Clip-bank lookups in `variant_glb.build()`** only matched keys named
  `<clip>.animation`, while `bake_v4` accepts bare names too; a bare-keyed
  bank silently missed every clip and fell back to 30 fps. Lookups are now
  tolerant the same way `bake_v4`'s are.

### Correctness

- `bake_v4`: the frame count came from quaternion tracks only; a clip whose
  longest track is positional had its position keys silently down-sampled.
- `jiggle_d6`/`jiggle_pass`: the sim→clip resample clamped the index but not
  the weight, so clips faster than the integration grid extrapolated past the
  last sim sample (and could overshoot the engine distance clamp). Clamped.
- `variant_glb`: face-first materials silently lost their specular layer (the
  face material block was a copy of the body block minus the
  `KHR_materials_specular` handling); one `try/except` around the face-synth
  import also swallowed per-pose errors and disabled all auto-pairing on the
  first bad pose — it now guards only the import and reports failing poses.
- `skeleton_records` and `parse_model_nodes.parse_node_aux` were
  little-endian-only; both are byte-order aware now (facade callers get
  console support with no signature change).
- X360 texture carve: the tile buffer sized width as `max(w, 32)` where every
  consumer aligns width up to 32; non-power-of-two widths over 32 blocks got
  their untiled tail zero-filled (blank PNG bands).
- `mediastream` vs `MediaStream`: the console-audio metadata pass compared the
  asset class against two different spellings, so at most one branch could
  ever match; both comparisons are case-insensitive now.
- Legacy-carved textures (`diffuse.png`, …) used names the texture index and
  MTL linker can't see; they now use the standard
  `<i>_<label>_<WxH>_<FMT>.png` scheme and link into OBJ materials.
- `kapow_props.parse` bounds-checks payload reads (truncated propbags return
  partial results with a `warn` entry instead of raising `struct.error`), and
  the dead `wc + 1 != k` validation actually warns now.

### CLI and library surface

- `hash` and `gendata` dispatch before the facade import: `watchmen hash` no
  longer imports numpy/Pillow/the data tables, and `watchmen gendata
  keys-import` — the documented recovery when `kapow_fragment_keys.pkl` is
  missing — no longer dies on the very import error it exists to fix.
- `kapow_fragment` raises `ImportError` instead of `SystemExit` when its key
  table is missing: `SystemExit` derives from `BaseException`, so it escaped
  every `except Exception` guard (pytest collection died with zero tests run;
  `import watchmenlib` could kill a host process). The CLI catches it (and
  `struct.error`) and prints an `error:` line; missing-table exit code is now
  2, not 1.
- `--limit N` on the extractor actually stops after N block assets, as its
  help always claimed.
- Stale docs/comments swept: the extractor's `OUT/streams/` claim, a dead
  `_RIG["skeletons"]` store and its misleading comment, a dead `stats`
  counter, `rig_glb`'s claim that its (legacy, caller-less) animation path
  decodes translations, `extract_skeletons`' description of the removed
  biped-name parent fallback, and the removed `sys.argv` snapshot note in
  `watchmen.py`.
- The key-count-cap regression test now actually fails when the cap is
  removed (it fed keys the dimension check rejected anyway, so it pinned
  nothing).

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
