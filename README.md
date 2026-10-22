# MadMapper study (course unit after Bluebeam Revu)

**Want to try the app?** See `MapStudio/README.md` for macOS/Windows setup, a test checklist and the current limitations, and write your findings in `NOTES-AND-BUGS.md`.


Target: **MadMapper 6.1.8 Demo for Windows** (GarageCUBE), installed at `E:\Games\MadMapperDemo 6.1.8`. Started 2026-10-21.

## Documents

| file | content |
|---|---|
| `01-binary-and-file-formats.md` | technology stack (Qt 6 / OpenGL / FFmpeg / OpenCV / Lua 5.3 + Python 3.8), install layout, `.madproject` folder and the binary `.mad` format (QDataStream, magic `0BADBABE`, header, top-level load order), encrypted `main.ldat` modules, OSC/attribute model, ISF material layout, the Ghidra workflow |
| `02-project-schema.md` | key-by-key schema of a `.mad` project recovered from the decompiled deserializers: surfaces (quad, lines, fixture, surface3D …), outputs, visuals, modules, timelines, mappings, settings; C++ class ↔ surface type |
| `03-materials-isf.md` | MadMapper's ISF dialect: folder layout, header grammar, every INPUT type with validation rules, GENERATORS and parameter binding, RENDER/RASTERISATION settings, the generated GLSL preamble and stage assembly, `#include`, the LED fixture shader |
| `04-osc-and-control.md` | the attribute tree, OSC address families, controls table (mappings) and compatibility rewrites |
| `05-guides-digest.md` | digest of the 32 PDF manuals shipped with the app (UI, workflow, shaders, lighting/laser hardware, modules, shortcuts, menus) |
| `06-feature-inventory-and-clone.md` | feature inventory of MadMapper vs our own application, what building the clone taught us, next steps |

## Our own application: `MapStudio/`

A PyQt6 + OpenGL projection-mapping app built from the recovered specifications (see `MapStudio/README.md`): stage with several outputs (fullscreen per screen, loopback buffers), corner-pinned quads with mesh warp and soft edges, images/movies/ISF materials with the MadMapper dialect and our own MadNoise/MadSDF/MadCommon include libraries, a complete `.mad` reader + importer, JSON projects, undo. Run with `MapStudio\.venv\Scripts\python -m mapstudio [project]`.

## Raw material (not in the git repository)

The Ghidra project, the decompiled functions, the string tables and the extracted guide texts are
derived from the MadMapper binary and manuals and stay on the study machine (`E:\Claude\MadMapperStudy`);
`.gitignore` excludes them. Only the notes, scripts and the app are versioned.


- `index/` — `functions.csv` (105,415 functions), `strings.csv` (45,689 strings → referencing functions), `magic_refs.txt`, categorised string lists (`mm_*.txt`), extraction scripts (`mm_strings.py`, `mm_grep.py`, `mm_dump_lists.py`, `mad_keys.py`, `mad_keys_diff.py`, `extract_guides.py`), `fixture_shader.glsl`.
- `guides-text/` — plain text of all 32 bundled PDF guides.
- `decompiled/batch1…7/` — 88 Ghidra-decompiled functions (`<addr>_FUN_<addr>.c`, `_index.txt` per batch).
- `ghidra/` — persistent Ghidra 12.1.4 project `MadMapper.rep` (fully auto-analysed, 686 MB), headless scripts `scripts/ExportIndex.java` and `scripts/DecompileMatching.java`, console logs.
- `.venv/` — Python venv with `pypdf` for the guide extraction.

## Reproducing a decompile

```
set JAVA_HOME=C:\Program Files\Eclipse Adoptium\jdk-21.0.12.101-hotspot
E:\Claude\ghidra\ghidra_12.1.4_PUBLIC\support\analyzeHeadless.bat E:\Claude\MadMapperStudy\ghidra MadMapper ^
  -process MadMapperDemo.exe -noanalysis -readOnly -scriptPath E:\Claude\MadMapperStudy\ghidra\scripts ^
  -postScript DecompileMatching.java E:\Claude\MadMapperStudy\decompiled\batchN 1412548d0+141254fb0 [max=N]
```

(`+` separates addresses because headless splits arguments on commas; a Java regex against function names works too.)

## Boundaries observed

- The shipped factory modules (`main.ldat`) are Crypto++ CFB-encrypted scripts; the key was deliberately not extracted.
- The demo cannot save projects, so the schema was recovered from the shipped sample projects plus the loaders, not from round-tripping. A licensed copy (student price 30 % off) would let `index/mad_keys.py` confirm the remaining unknowns cheaply.
