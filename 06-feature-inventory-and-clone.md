# MadMapper 6.1.8 feature inventory vs MapStudio

Educational, supervised study. The inventory is compiled from the 32 bundled guides (`05-guides-digest.md`), the UI strings and the decompiled loaders; MapStudio (`MapStudio/`) is our own PyQt6 + OpenGL application that re-implements the core of it. No MadMapper code or assets are copied: the `.mad` reader, the ISF dialect and the include libraries were written from the recovered specifications.

## How MadMapper models a show (what we learned)

- **One stage, many outputs.** Every projector/output is a rectangle on a shared 2D plane (`position` = centre, `stageSize` = extent, 6.4 x 3.6 for 16:9). Surfaces are placed in that plane with absolute coordinates and are drawn by whichever output covers them. Soft-edge blending across projectors is just two surfaces of the same media with overlapping input regions. MapStudio uses exactly this model.
- **Output geometry vs input geometry.** A quad has four output corners (`positions`, projective "Perspective" or affine) and an input rectangle in media space (`uvs`, 0..1 with (0,0) bottom-left; values outside the media are black). `positionUv/scaleUv/rotationUv` and `position/rotation/scale` are derived from those polygons (centre and size), not independent state. MapStudio stores the two polygons.
- **Media are "visuals" with attributes.** A visual record is `url` + `type` + `attributes` keyed by the parameter *label path* (`Color/Front Color`), which is how MadMapper survives shader renames. Materials are ISF folders rendered to a texture of a chosen size; generators, movies, images, live inputs and output loopbacks share the same record. MapStudio keeps the same five kinds (image, movie, material, built-in generator, output loopback) and converts label-keyed values to input names on import.
- **Draw order is list order, foreground first.** The surfaces list shows the top-most surface first; groups toggle visibility of their children (`surfacesRelations` holds the parent index). MapStudio reverses the list on import and flattens groups.
- **Everything is an attribute.** Surfaces, media, outputs and modules expose a tree of attributes that is simultaneously the inspector UI, the OSC address space (`/surfaces/2/opacity`) and the controls table. MapStudio only has the inspector side of this.

## Gap analysis

Legend: done = implemented and verified in MapStudio 0.2 · partial = implemented with reduced scope · missing = not implemented · out of scope = not planned for this study (hardware I/O, licensing, cloud).

### Surfaces
| MadMapper | MapStudio 0.1 |
|---|---|
| Quad with 4-corner perspective or affine mapping | done |
| Triangle, Circle, Mask ("black hole") surfaces | done (0.2); Polygon surfaces missing |
| Mesh warping (grid, Alt+click to add points, Bezier handles, precision) | partial: regular grid warp with draggable nodes and a spline "Smooth" option; no tangent handles, no point insertion |
| Layer masks with feathering and attachment | partial (0.2): polygon mask per quad/circle edited in the input view, invert, feather (blur); no attachment modes |
| Soft edge per side with width, curve and gamma | done (curve/gamma formulas are our own reading) |
| Opacity, modulation colour, blend modes (ignore alpha, add, over, premultiplied, multiply, subtract) | done |
| Stencil / silhouette blend modes | partial: drawn as "over" |
| Surface FX (`FX/<Name>` ISF with vertex stage, e.g. Rutt Etra, Color Controls) | done (0.2): all 23 factory FX compile and run, instancing and vertex displacement included; parameters imported by label; affine input matrix |
| Groups, lock, visibility, duplicate, z-order | done (groups flattened; visibility inherited on import) |
| Lines (textured Bezier paths), 3D surfaces (OBJ, calibration points), fixtures (LED), laser surfaces | out of scope |

### Media
| MadMapper | MapStudio 0.1 |
|---|---|
| Images, movies (FFmpeg, loop, speed, audio) | done for images and movies (Qt Multimedia, muted audio); no scrubbing |
| ISF materials with the MadMapper dialect (INPUTS, GENERATORS, generate_as_define, `#include`, MadNoise/MadSDF/MadCommon) | done: all 42 shipped materials parse, assemble and compile with our own include libraries |
| Material parameters in the inspector grouped by label path | done (float, int, bool, long, color, point2D, point3D/4D, floatRange) |
| Hot reload of edited shaders | done (file mtime watch) |
| Imported textures, `REQUIRES_LAST_FRAME` | done |
| Audio / audioFFT inputs, curve editor | partial: curve becomes a lookup texture; audio inputs bind an empty texture |
| Factory generators (Test card, Solid colour, Grid, Text, Colour patterns, Movie folder player, particles, Chrono, Count down) | partial: Test card and Solid colour built in; others skipped on import |
| Live inputs (cameras, NDI, Spout/Syphon), output loopback | partial: output loopback (video buffers) done; cameras/NDI/Spout missing |
| Timelines / scenes / cues, montages, media playback module | missing |
| Code editor, MadAI material generation | missing |

### Outputs
| MadMapper | MapStudio 0.1 |
|---|---|
| Multiple video outputs on screens, fullscreen (Cmd+U / Cmd+T), desktop window mode | done (Ctrl+U / Ctrl+T, "Open as window") |
| Test pattern, output background/mask images, frame delay, MSAA | partial: test pattern only |
| Output masks and soft-edge per output | missing (soft edge is per surface, as in MadMapper) |
| Publish to Syphon / Spout / NDI, Blackmagic | out of scope |
| DMX / Art-Net / sACN outputs, laser outputs | out of scope |

### Project and files
| MadMapper | MapStudio 0.1 |
|---|---|
| `.madproject` folder with binary `.mad` (QDataStream) | done: full reader for the Qt 4.8 wire format incl. MadMapper's user types (`MadColor`, `IndexFloatMap`, `IndexVariantMap`, `FilePath`); all six sample projects parse completely |
| Import into our model | done for video outputs, quads, images, movies, materials (library or project copies), loopbacks, test card, solid colour; report lists what was skipped |
| Save / autosave / backup / merge | partial: JSON `.mapstudio` save/load with relative media paths; no autosave/merge |
| Undo / redo | done (snapshot based, 100 steps) |
| Export to MiniMad, project conversion 5 to 6 | out of scope |

### Control
| MadMapper | MapStudio 0.1 |
|---|---|
| OSC in/out with OSCQuery, MIDI, DMX in, Art-Net in, keyboard, Stream Deck, modules (Lua/Python) | partial (0.2): OSC server with MadMapper-style addresses (`/surfaces/<sel>/opacity`, `/medias/<sel>/assign`, `/outputs/<sel>/show_test_pattern`, `/master/*`, `/custom/BPM/bpm`, `soft_edge/*`, `fx/*`), queries answered, feedback target; no OSCQuery, MIDI, DMX or modules |
| Global BPM, Ableton Link, tap | partial: BPM value used by `time_base` generators (bpm_sync, link_speed_to_global_bpm) |
| Controls list, learn, mappings | missing |

### UI
| MadMapper | MapStudio 0.1 |
|---|---|
| Input view / Output preview split, surfaces tab, outputs tab, media panel, inspector | done |
| Drag corners, drag surface, arrow nudges, Tab cycles handles, Shift snaps, wheel zoom, Alt/middle drag pans, F fits | done |
| Right-click menu (duplicate, delete, reset, enable warp, perspective toggle) | done |
| Scenes/cues grid, timeline editor, fixture editor, DMX monitor, library browser with thumbnails | missing |

## What the clone taught us about the original

- MadMapper's "stage units" are not pixels: an output's stage height is always 3.6 and the width follows the pixel aspect; the loopback output of the soft-edge example (1728 x 1117) is 9.667 x 3.6 only because it was set to a 145:54 ratio.
- The soft-edge sample works by giving both projector surfaces an input rectangle wider than the media (u from -0.84 to 0.83 and 0.16 to 1.84) so that each projector shows half of the loopback plus a 40 % overlap; outside-media pixels are black. Reproducing this is what forced the "outside the media is transparent" rule in our shader.
- Generators are evaluated on the CPU once per frame and uploaded as `uniform float`; a material with 40 inputs and 4 generators costs nothing on the GPU side.
- `generate_as_define` produces `#define <NAME>_IS_<Value>` for the selected option and the shader is recompiled when the option changes. The shipped `MadNoise.fs` relies on it (`#if defined(TYPE_IS_Worley)`).
- The shipped header JSON is not strict JSON: trailing commas, `1.` and `.5` number spellings and `"FLAGS": "button,trigger"` appear in the factory library, so MadMapper's parser is lenient. We had to be equally lenient to load the library.
- The video-frame path matters: converting a decoded frame lazily crashed Qt's FFmpeg backend; frames must be converted when they arrive. MadMapper's "Video Buf Size" and decoding-strategy attributes hint at the same buffering problem on their side.

## What version 0.2 added (and what it taught us)

- Surface FX: the shipped FX only need the interface described in the "Empty Template" comment block (`mm_Vertex`, `mm_TexCoord0`, the two matrices, `mm_FragNormCoord` and friends) plus `inputImage` as an ordinary ISF image. Rutt Etra keeps its ISF header in the `.vs` and relies on `RENDER_SETTINGS/INSTANCE_COUNT` bound to a `multiplier` generator, so instancing is part of the dialect.
- FX parameters are stored in the project by *label* (`FX/Rutt Etra/Line Count`), exactly like media attributes, and enum values by their label string.
- MadMapper's own "Empty Template" puts an ordinary comment before the ISF directive, so the header scanner must skip non-directive comments.
- Masks, triangles and circles share the quad loader; a circle is the ellipse inscribed in its quad.
- OSC: MadMapper addresses surfaces by name (v4 guide) or id (project files); MapStudio accepts both and `selected`.

## Next steps if the course continues

1. Polygon surfaces and MadMapper's mask attachment modes; Bezier tangent handles and point insertion for mesh warps.
2. Timelines/scenes: snapshot the surface and media attributes into cells, with per-parameter transitions.
3. Live inputs (cameras via Qt Multimedia, NDI), MIDI learn on top of the OSC tree, OSCQuery.
4. Export back to `.mad` (the writer side of the QDataStream format).
