# MadMapper — digest of the 32 bundled guides (`Resources\Guides\*.pdf`)

Full text is in `guides-text\*.txt` (extracted with pypdf, `index\extract_guides.py`). Several guides date from MadMapper 4/5 and refer to "Cues" where v6 says "Timelines"; facts below are as written in the guides.

## Core workflow

- **Introduction to the User Interface**: four areas — Media Panel (right), Views (Input view, Output preview), Project Tabs, Tool Panels; tooltip status bar at bottom. Media categories: Generators, Materials, ISFs (no multi-pass), Quartz Composer, Images, Movies, Images Folders, Live Input, Syphon/Spout/NDI. Project tabs: Surfaces (Quad, Line, Triangle, Circle, Mask, 3D Surface, Group), Fixtures (DMX Line, DMX Circle, Group), Projectors/Outputs, Modules, Master. Master levels: Master, Video, DMX, Audio; Freeze Engine; Freeze Video/DMX output. Material GLSL max 4.1 on Mac, 4.5 on Windows.
- **My First Video Mapping**: Projector tab ▸ Output Destination; Show Test Pattern; fullscreen Output ▸ Fullscreen Mode (Cmd+U, Cmd+T exits); turn off display mirroring; Surfaces tab first icon adds a Quad; Media tab ▸ Movies "+" then arrow to assign; File ▸ Save Project.
- **Mesh Warping**: Perspective checkbox moves corners; Alt+click adds warp points; right-click ▸ Remove Horizontal/Vertical; Bezier checkbox; Precision controls polygon smoothness; Alt+B locks affine transforms while editing; grid generator as test content (e.g. 10×23, 50 % opacity, additive).
- **Masking**: Project ▸ Add Mask or Alt+A on a selected quad; Enter closes the path; Alt+click adds a point; Delete removes; right-click point toggles Bezier, right-click handle links/unlinks tangents; layer masks have feathering (Inside/Outside/Centered) and attachment (Nothing/Quad/Input); a mask surface is a "black hole".
- **Scenes and Cues**: scenes sit in row 1 and snapshot surfaces, fixtures and media; the grid defaults to 16×8 and grows; Edit mode (Cmd+Shift+C) vs Live mode; per-parameter transitions ("Fade: …"); Backspace removes a parameter from a cue; Shift+click edits without adding; controls can "Map to Cell Position" or "Map To Cue"; per-column Auto Play in seconds or beats.
- **Preferences**: Workspace folder (FXs, Generators, ILDA, MadLight sequences, Materials, modules, vector materials; default Documents/madmapper); OSC input port 8010, feedback port/IP, Bonjour; MIDI input/feedback devices; DMX Output ArtNet/sACN/USB-DMX (Enttec Pro/mk2, garageCube), max FPS 44 or 60, unicast, route ArtNet to USB LED; Engine FPS Auto/Manual, double-buffered preview; Misc: Silent Mode, Blackmagic drivers, Leap Motion, Kinect Masker (deprecated), extended toolbar; Controls: Enable Stream Deck.
- **The MadMapper FAQ** / **Knowledge Base**: requirements and demo limits (as in `01`); licences: rental = 1 computer, perpetual = 1 seat + spare, max 2 authorised computers, one remote reset per year; protocols Art-Net and sACN only; Art-Net universe = net×256 + subnet×16 + universe, software limit 4096 universes; one MIDI note per control; Blackmagic outputs unsupported; MTC via right-click movie position ▸ Add MIDI control ▸ Time Code; Ableton Link button in Master tab; Windows multi-channel audio needs ASIO; Teensy preferred over Arduino Uno for LEDs.

## Shaders

- **Materials Documentation**: folder = thumbnail + `.fs` (+ optional `.vs`); `materialColorForPixel(vec2)`; GLSL 150 core default; INPUT types floatRange, color (`no_alpha`), long enum (`generate_as_define`), bool (`button`), int/float; IMPORTED 2D/cube/3D (DEPTH); GENERATORS time_base (speed, reverse, speed_curve, strob, bpm_sync), animator, damper (hardness 0.1, damping 0.8), adsr, linear_filter, multiplier, incrementer, pass_thru; RASTERISATION_SETTINGS DEFAULT_RENDER_TO_TEXTURE, DEFAULT_WIDTH/HEIGHT, REQUIRES_LAST_FRAME (`mm_LastFrame`); audio inputs `audio` (SIZE ≤ 512) and `audioFFT`.
- **Surface FX Documentation**: 2D FX (Quad/Triangle/Circle), 3D FX, Line FX; `fxColorForPixel(vec2 mm_FragNormCoord)` + optional `fxVsFunc`; MEDIA dictionary REQUIRES_TEXTURE / GL_TEXTURE_*; inputs prefixed `fx_`; macros FX_NORM_PIXEL, FX_IMG_SIZE (1024² for materials), FX_NORM_PIXEL_LOD, FX_TEXEL_FETCH; `IS_MATERIAL` define.
- **Laser Materials Documentation**: `laserMaterialFunc(pointNumber, pointCount, out pos, out color, out shapeNumber, …)`, default 8192 points; RENDER_SETTINGS POINT_COUNT, MAX_SPEED (1, max 4), SKIP_BLACK, PRESERVE_ORDER, ANGLE_OPTIMIZATION, ANGLE_THRESHOLD, ANGLE_MAX_DELAY, FIRST/LAST_POINT_REPEAT, POLY_FADE_IN, MIN_ILDA_POINTS_PER_POLYLINE; previous frame via `mm_LastFrameData`.
- **MadNoise** (`#include "MadNoise.glsl"`): vnoise, simplex noise, worley, flow, billowed, ridged, curl; fBm(p, octaves, lacunarity, gain), billowyTurbulence, ridgedMF; derivative variants; `NOISE_TEXTURE_BASED` with an imported LUT.
- **MadSDF** (`#include "MadSDF.glsl"`): circle, rectangle, roundedRectangle, triangle, hexagon, line, arc; fill, stroke, glow; blend, smoothBlend, subtract, intersect; translate, rotate, transform, repeat, repeatRadial.
- **Realtime Reactive Visuals**: Code editor "+" creates a material from Empty Template; JSON header builds the UI; MIDI-drive inputs (Ableton example).
- **MadAI Cheat Sheet**: prompt vocabulary for the AI material generator (shapes, lighting, noise, camera, animation terms).

## Lighting, laser, hardware

- **USB to LED**: Teensy 3.1/3.2 + FastLED serial sketch; Preferences ▸ DMX Output ▸ ArtNet ▸ route to USB LED devices; universe 0 → Teensy; Fixture Editor "+" to define pixels.
- **MadLaser Guide**: DACs Etherdream, Helios USB, ShowNET, Pangolin FB4; ≤ 45 kpps advised; ILDA FPS = PPS / point count; output settings (Desired FPS, Blank Delay, Color Levels, Time Shift, Safety Area, Masks); vectorisation Find Paths / Find Contours (Canny) with filtering; > 2,000 paths aborts; laser text via stick fonts.
- **MadLaser AVB Support**: laser over AVB/Dante audio (RME Digiface AVB), 48/96 kHz, LA Toolbox config, Preferences ▸ Laser ▸ Enable audio Laser.
- **Laser Scanner Guide** / **Space Scanner Guide**: Sony (Smart Remote Control over Wi-Fi) or Canon (M mode over USB), webcams and NDI also; manual focus/exposure; Tools ▸ Space Scanner → result becomes the Video Output's background image; Sony needs 5.3+.
- **MadProjectorControl Guide**: PJLink projectors; one PJLink module per projector; discovery ≤ 30 s or Custom IP + password; power, mute, info.
- **Arduino Firmata**: Uno/Mega/Teensy with StandardFirmata(Plus); Firmata module ▸ port/model ▸ pin modes (PWM, analog); Uno can't do PWM and Servo together.
- **MINIMAD_USERGUIDE**, **MiniMad Controller**, **My First MiniMad Video Export**: Raspberry Pi 2 player, 1080p60 HDMI, Video or Light firmware; video export limited to Quad/Triangle/Circle/Mask, one media per surface, 4 GB files; OSC port 1111; Bonjour discovery; playback modes; CRF encoding; keyboard controls on the device.

## Modules

- **Modules** (overview), **Cue Scheduler** (Schedule/Automate/Cue/Manual tabs, date fields accept "Each", auto-play every N s or N beats, loop/random, skip empty), **Calendar Scheduler** (ICS import, event name = scene/cue name, recurring events 365 days ahead), **Control Surface** (APC mini mk2, APC40 mk2, Launchpad MK2/Mini Mk3/X; 5.4+), **Weather & Pollution** (OpenWeatherMap key; outputs incl. PM2.5/PM10), **Stream Deck Plugin** (5.4+; Scene/Cue Launcher keys; Parameter Controller dials fed by a pasted OSC address), MIDI Out (CC, Note On/Off, Note Trigger, Pitch Bend; loopMIDI on Windows), OSC Out (Float 0–1, unbounded, Integer, Boolean, Nil, String; send now / on change; feedback), Oscillator / 2D / Bank (Sin, Triangular, Saw, Square, Noise; relative or BPM timing; speed, phase, range, offset), DMX Router (ArtNet/sACN universe → USB DMX device).

## Shortcuts (collected)

| Key | Action |
|---|---|
| Alt+A | Add mask (Masking) / Add laser path (MadLaser) |
| Enter | Close mask or line path |
| Alt+click | Add point to mask path or warp grid |
| Delete | Remove point / media / cue parameter |
| Ctrl/Cmd+C, V | Copy / paste mask, cue, laser path |
| Ctrl/Cmd+D | Duplicate laser path / text generator |
| Cmd+U / Cmd+T | Fullscreen output / exit |
| Ctrl/Cmd+S | Save project |
| Cmd+Shift+C | Cue edit mode |
| Alt+B | Lock affine transforms |
| Shift+click | Multi-select surfaces; edit cue parameter without adding |
| Alt+drag cue | Duplicate cue |
| Arrow keys / Tab | Nudge handle / next handle |
| Ctrl/Cmd+click Tools menu | Enable log |

## Menus and panels (as named in the guides)

File ▸ Import Media, Save Project, Export Video Mapping to MiniMad, Import SVG · Project ▸ Add Mask, Add Laser Path · Edit ▸ Controls List · Cues ▸ Edit · Output ▸ Fullscreen Mode, Show Info, Show Laser Cursor · Tools ▸ Space Scanner, LED Scanner, Laser Scanner, MadLight Recorder, Enable Log, Send Current Log · Account/Help ▸ Manage Authorisations, De-authorize · Preferences sections: Workspaces, MIDI, OSC, DMX Input, DMX Output, Audio, Engine, Misc, Laser, Controls · Tool panels: Scenes and Cues, Control List, Library, MadLight Recorder, DMX Monitor, Fixtures Editor, Code Editor · Inspectors: Surface (Blend Mode, Opacity, Perspective, Colors, FX, Mesh Warping, Bezier, Laser Render), Output (Destination, Size, Test Pattern, Background, Mask, Desktop window, Publish to Syphon/NDI), Module, Fixture, Media.
