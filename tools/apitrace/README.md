# Reading the D3D9 captures (`atx`)

`atx.c` is a small seekable reader for apitrace files (snappy container, trace
version 6). `apitrace dump` scans a trace from the start, which takes minutes
on the multi-gigabyte gameplay captures; `atx` indexes a trace once (one
checkpoint per `Present`) and then dumps any frame directly. It is a research
tool: nothing in the toolkit calls it, and the captures are not shipped.

Build (no snappy headers needed):

    gcc -O2 -o atx atx.c -l:libsnappy.so.1

Use:

    atx index TRACE SIGS IDX [seconds]      full scan; one checkpoint per Present
    atx dump  TRACE SIGS IDX F0 F1 [filters] [blobfile min [max [callsfile]]]

- IDX line: `frame next_call event_no chunk_file_offset offset_in_chunk`
  (the state after the Present).
- SIGS: every function / enum / bitmask / struct signature with the event
  number that defined it, so a dump can start at any checkpoint.
- filters: comma list, substring of the call name; `=Name` means the name
  must end with Name.
- `dump F F+1` covers the calls of frame F.
- Floats are printed with `%.9g` (float32 exact); blobs as
  `blob(size,fnv=,crc=[,at=offset in blobfile])`.

Checked against `apitrace dump` 14.0 on one frame (6,674 calls): call numbers
and names identical, argument text identical on the six call types compared.

What the renderer notes in `docs/ENGINE_CONSTANTS.md` and the cube-map rule in
`docs/LEVEL_META.md` were measured on:

| capture | size | frames | calls | content |
|---|---|---|---|---|
| `KapowMulti.trace` | 98 MB | 410 | 897,193 | main menu |
| `KapowMulti.1.trace` | 4.5 GB | 7,643 | 47,249,721 | Bordello |
| `KapowMulti.2.trace` | 5.8 GB | 9,723 | 60,195,713 | Bordello |
| `KapowMulti.3.trace` | 11.3 GB | 15,887 | 135,817,432 | NightClub |

Frame time: VS c9 of `Deferred main soft alpha` / `Reflection - Main` is a
sheet's scroll offset, which advances by scroll speed × the scaled game step
(0x5231de, `[0xe14308]`). Two sheets serve as clocks in the Bordello captures:
Rorschach's ink blots (−0.03, 0.019 per second) and one with (−0.078, −0.026);
Δx / speed_x = Δy / speed_y = the step in seconds, a whole number of
milliseconds at time multiplier 1 (12–19 ms in trace 1 frames 5121–5169).
Shader text: `atx dump TRACE SIGS IDX 0 N CreatePixelShader` prints the
disassembly of all 150 pixel shaders of trace 1; the main-pass variants are
calls 1223, 1122, 1123, 1026, 1027, 1028 (hard and soft alpha) and 1029, 1036
(fall-off).

A frame holds what a comparison with the export needs: the shader text, every
constant register (VS c4–c7 = the object's world matrix in the `Deferred main` passes (world ×
view × projection in `Depth info`), c40… = the bone
palette; PS c2, c11, c12, c14 = the sheet values), the bound textures with
their uploaded bytes, and the render state.
