# MapStudio

An educational projection-mapping application modelled on MadMapper, written for the course unit
documented in the parent folder (`../01-*.md` to `../06-*.md`). Python 3.12, PyQt6 6.11,
OpenGL 4.1 core. It runs on Windows and macOS (Linux should work but is untested).

## Running on macOS

1. Install Python 3.12 (python.org installer or `brew install python@3.12`).
2. In a terminal:

   ```
   cd MapStudio
   python3.12 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python -m mapstudio
   ```

3. If MadMapper (or its demo) is installed, point MapStudio at its `Resources` folder so the
   material and FX libraries appear in the menus. The default locations
   `/Applications/MadMapper.app/Contents/Resources` and `/Applications/MadMapper Demo.app/Contents/Resources`
   are tried automatically; otherwise set it before launching:

   ```
   export MADMAPPER_RESOURCES="/Applications/MadMapper.app/Contents/Resources"
   ```

4. To open one of MadMapper's sample projects:

   ```
   python -m mapstudio "/Applications/MadMapper.app/Contents/Resources/SampleProjects/Video Example.madproject"
   ```

Without MadMapper installed the app still runs with its built-in test card and solid colour, your
own images and movies, and any ISF material folder you point it at.

Running on Windows is the same with `py -3.12 -m venv .venv` and `.venv\Scripts\python -m mapstudio`.

Tests: `python -m pytest -q tests` (tests that need the MadMapper library skip when it is absent).

## What to test

Work through these in order and note anything odd in `../NOTES-AND-BUGS.md`.

1. **Startup**: the window shows a test card on one quad inside "Output-1". The status bar shows the frame rate (expect about 60 fps).
2. **Stage editing**: drag the yellow corner handles, drag inside the quad to move it, scroll to zoom, middle-drag or Alt+drag to pan, press F to fit. Arrow keys nudge (Shift = x10), Tab cycles handles.
3. **Input editing**: with a surface selected, drag the blue corners in the left view to crop or stretch the media; double-click resets.
4. **Media**: Media panel, "+ Add" an image and a movie, then "Assign to surface". Try a library material (needs MadMapper) and change its parameters in the Inspector.
5. **Shapes**: Project menu, add a Triangle, a Circle and a Mask. Masks are black polygons; drag their points.
6. **Layer mask**: select a quad, Inspector, "Edit mask in input view", drag the magenta points, Alt+click adds, right-click removes, try Invert and Feather.
7. **Mesh warp**: Inspector, "Enable / reset grid", drag grid nodes, toggle "Smooth".
8. **Soft edge**: enable in the Inspector, raise Left/Right widths, change curve and gamma.
9. **Surface FX** (needs MadMapper): Inspector, Surface FX, choose "Color Controls" or "Pixelate" and move the sliders; "Vertex Noise" and "Rutt Etra" bend the geometry.
10. **Outputs**: Outputs tab, pick a screen, "Fullscreen on screen" (Ctrl+U) and back (Ctrl+T or Esc). Add a second output; drag its label on the stage to move it. "Open as window" shows a windowed preview.
11. **Edge blending**: add a loopback media ("+ Add" > Output loopback) of one output and show it on two overlapping quads with soft edges, as in the MadMapper SoftEdge sample.
12. **MadMapper import**: File > Import MadMapper project (a `.mad` file). The report lists what was skipped. Compare with MadMapper's own rendering.
13. **Save / load**: Ctrl+S to a `.mapstudio` file, reopen it; media paths are relative to the file.
14. **Undo / redo**: Ctrl+Z / Ctrl+Y after each kind of edit.
15. **OSC**: open the OSC dock (tab next to "Project"), enable the port, send `/surfaces/selected/opacity 0.5` from any OSC app (TouchOSC, Max, `oscsend`); the dock logs every message and lists all addresses.

## Current limitations

- Surfaces: no lines, 3D (OBJ) surfaces, LED fixtures or lasers. Groups are flattened on import. Mesh warp is a grid with optional spline smoothing, not MadMapper's Bezier tangent handles. Layer masks are polygons without MadMapper's attachment modes; feathering is a blur.
- Media: no cameras, NDI, Spout/Syphon, timelines/scenes/cues, montages, audio-reactive inputs (audio and audioFFT inputs are bound to an empty texture). Movies are muted. Only the test card and solid colour generators exist; other MadMapper generators are skipped on import.
- FX: the input-rectangle matrix is affine (a non-parallelogram input quad is approximated); `IS_MATERIAL` is never defined (the material is always rendered to a texture first). Stencil and silhouette blend modes draw as "over".
- Outputs: no output masks, background images, frame delay, MSAA or publishing to Syphon/Spout/NDI.
- Control: OSC only (no MIDI, DMX, Art-Net, keyboard mapping). OSC feedback is sent only in reply to a query.
- Files: MadMapper import is read-only (no export back to `.mad`). Surface FX colour inputs imported from projects are untested (no sample has one).
- Verified by scripts and screenshots on Windows; mouse interaction and macOS have not been checked by a person yet.

## Controls

| Where | Action |
|---|---|
| Stage view | click selects a surface; drag a corner handle (or warp node); drag inside moves the surface; drag an output's label moves the output; wheel zooms; middle or Alt+drag pans; **F** fits all; **Shift** while dragging snaps |
| Stage view keys | arrows nudge the active handle or the surface (Shift: x10); **Tab** cycles handles; **Esc** deselects; **Delete**; **Ctrl+D** duplicate; **Ctrl+]** / **Ctrl+[** z-order |
| Stage view right-click | duplicate, delete, reset to rectangle, enable/reset/disable mesh warp, perspective/affine |
| Input view | drag the blue corners to crop/stretch the media; drag inside to move the input rectangle; double-click resets; in mask-edit mode drag magenta points, Alt+click adds, right-click removes |
| Media panel | **+ Add** (image, movie, material folder, solid, test card, loopback, MadMapper library material); double-click or **Assign to surface** |
| Outputs tab | screen, pixel size, stage centre, test pattern, fullscreen / window / close |
| OSC dock | enable, port (default 8010), feedback host/port, log, address list |
| Menus | Ctrl+N/O/S, Ctrl+I import MadMapper project, Ctrl+Z/Y undo/redo, Ctrl+U / Ctrl+T fullscreen on/off, Ctrl+Shift+T test pattern, Alt+A add mask |

On macOS use Cmd where Ctrl is written.

## Layout

```
mapstudio/
  madfile/   qvariant_stream.py  pure-Python QDataStream/QVariant reader (Qt 4/5/6 wire ids, user types)
             madproject.py       .mad header, MadMapper user types, polygon blobs
  model/     project.py          Project / Output / QuadSurface (quad, triangle, circle, mask) / Visual, JSON
             persistence.py      .mapstudio save/load
             mad_import.py       MadMapper -> MapStudio import with report
  isf/       header.py inputs.py generators.py assembly.py material.py fx.py; glsl/ include libraries
  render/    gl.py engine.py materials.py fx.py media.py geometry.py; builtin/ test card + solid colour
  osc/       protocol.py (codec) server.py (UDP) tree.py (address tree)
  ui/        app.py main_window.py gl_views.py panels.py
tests/       pytest suite (62 tests)
tools/       mad_probe.py isf_check.py gl_check.py fx_check.py headless_frames.py ui_exercise.py shapes_demo.py
```

Rendering: one offscreen engine context renders materials and loopback outputs into textures each
frame; the stage view, input view and output windows are `QOpenGLWidget`s sharing those textures
and draw the surfaces with a projective corner-pin shader (or the surface's FX program).

## Verification done

- `tests/`: 62 passing.
- `tools/gl_check.py` on the MadMapper material library: 42 compiled, 0 failed; `tools/fx_check.py`: 23 FX compiled for quad, triangle and circle.
- Screenshot runs (`python -m mapstudio <project> --screenshot DIR`) of the default project, the shapes demo (`tools/shapes_demo.py`), the MadMapper Video Example (Rutt Etra FX) and the SoftEdge Blending example.
- `tools/ui_exercise.py`: scripted pass over inspector, material parameters, undo/redo, surface and output actions, media adding, output windows and save/reload.
