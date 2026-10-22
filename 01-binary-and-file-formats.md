# MadMapper 6.1.8 (Windows demo) — binary, stack and file formats

Study date: 2026-10-21. Install: `E:\Games\MadMapperDemo 6.1.8` (installer `MadMapperDemoSetup.exe`, ~250 MB).
Evidence sources: install-folder inventory, string extraction from `MadMapperDemo.exe` (45.7 MB, PE x86-64, SHA-256 `b081839f…c382a8c5`), and the bundled sample projects. Decompiled source is not available: MadMapper is native C++, so unlike Revu (.NET, dnSpy) there is no readable intermediate code. Strings, imports, RTTI names and Qt meta-object names survive, and those are what this document is built from.

Extracted indexes live in `index/` (`mm_strings.py` → `mm_dump_lists.py` produce them; `mad_keys.py` dumps a `.mad` file).

## 1. Technology stack (from imports and RTTI)

| Layer | Evidence | Notes |
|---|---|---|
| UI framework | `Qt6Core/Gui/Widgets/OpenGL/Network/Xml/SerialPort/Svg/Core5Compat.dll`, `Ui::SurfaceTab`, `Ui::MediaTab`, `Ui::OutputTab`, `Ui::ModuleTab`, `Ui::MasterTab`, 1,554 Qt signal/slot signatures, `Resources/app.css` (130 KB Qt stylesheet with `$variables`) | Qt 6 Widgets, custom frameless window (`QGoodWindow`). The four main tabs map 1:1 to the docs' Surfaces / Media / Outputs / Modules panels plus Master. |
| Rendering | `OPENGL32.dll`, `glew32.dll`, `dxcompiler.dll`/`dxil.dll`, `#version 150 core` shaders, `GraphicsScene::renderDmxOutput / RenderFixtures / renderLaserSurfaces`, `GraphicsView::render` | OpenGL 3.2+ core profile (matches the docs' "OpenGL 3.3" requirement). DXC is present, probably for Spout/DX11 interop or an HLSL path. |
| Engine framework | RTTI namespace `madam::` (Timeline*, ScriptCommand, EventCallback, AttributeCallback, ChannelCallback, MadReceiver), classes `MadNode`, `MadEntity`, `MadRouter`, `MadResourceRegistry`, `MadCommandHandler`, `MMModule`, `MMVisual` | Internal framework called **MadFramework / "madam"**. A path baked into the sample project gives the repo layout: `…/GitHub/mad_framework/madframework/master/MadFramework/Applications/MadMapper/app/src/resources/SampleProjects/`. Attributes + channels + commands look like the central data model (see §4). |
| Scripting | `python38.dll` + full `Lib/` stdlib (1,198 .py), `PyInit_mad`, `PyInit_nvg`, `PyInit_service`, `main.py`; Lua 5.3 (`LUA_PATH_5_3`, `main.lua`, `luaopen_%s`, `LUABOX`); `Resources/MadamScripting.dat` (23 MB Qt resource bundle, contains fonts etc.) | Two embedded script runtimes. Modules ship as `main.ldat`, which is not plain text (high-entropy, no magic) — almost certainly encrypted/compressed Lua or Python. Python exposes `mad`, `nvg` (NanoVG) and `service` modules. |
| Video | `avcodec-61 / avformat-61 / avfilter-10 / avdevice-61 / swscale-8 / swresample-5` (FFmpeg 7.x), `MF.dll`/`MFPlat`/`MFReadWrite` (Media Foundation), HAP/ProRes, H264 encoder (4K/8K limit message) | FFmpeg for decode and timeline export; Media Foundation and DirectShow for capture. |
| Texture sharing | `Processing.NDI.Lib.x64.dll`, Spout (`spoutGL::`, `spoutDirectX::`, `MadSpoutSender`), Syphon strings (mac only) | NDI send/receive, Spout on Windows. |
| Computer vision / 3D | `opencv_*454.dll` (core, imgproc, calib3d, features2d, objdetect, dnn, stitching, video…), `realsense2.dll`, `freenect2.dll` (Kinect v2), `Leap.dll`, `EDSDK.dll` (Canon DSLR), `haarcascade_frontalface_alt2.xml` | Space Scanner / LED Scanner / 3D calibration use OpenCV 4.5.4; depth cameras feed the "Depth Masker" generator. |
| Lighting | `libShowNet.dll`, `ftd2xx.dll` (FTDI USB-DMX), `libusb-1.0.dll`, Art-Net/sACN strings (`artNetRoutingTables`, `sacnPriority`, `*.madart` routing files), ILDA DACs (Etherdream, Helios, ShowNet, FB4, PONK) | 1,412 DMX/Art-Net related strings — the lighting side is as large as the video side. |
| Input | `SDL2.dll` (`/io/services/sdl2gamecontroller`), XInput, RtMidi, RtAudio, DirectSound, Firmata (serial), Leap Motion | |
| Network | asio/websocketpp (`transport::asio::`), Bonjour (`MadMasterBonjourBrowserThreadObject`), HTTP (`MadHttpGet/Post/Delete`), `/madam/http_server`, Ableton Link, PJLink, OSCQuery | A built-in HTTP server exists (used by OSCQuery and the Stream Deck plugin). |
| Crypto / licensing | `libcrypto-1_1 / libssl-1_1`, CryptoPP RTTI, `DemoManager`, `LicenseDelegate`, `checkupdate.madmapper.com/file/%1.txt` | |
| Serialization | `QJson::ParserRunnable/SerializerRunnable`, `serialization::archive` (Boost.Serialization), `QDataStream`-style project files | |

## 2. Install folder layout

```
MadMapperDemo.exe             main binary (everything is statically linked except the DLLs above)
*.dll                         Qt6, FFmpeg, OpenCV, NDI, RealSense, Python 3.8 runtime …
Lib/                          Python 3.8 standard library (+ pip/setuptools), no MadMapper-specific .py
platforms/ imageformats/ …    Qt plugins
Resources/
  app.css                     Qt stylesheet for the whole UI (themeable via $tokens)
  MadamScripting.dat          Qt .rcc resource bundle for the scripting/editor layer (fonts, …)
  output_background.png
  Materials/        (43)      generative ISF materials — one folder each: Name.fs + .info + thumbnail
  LaserMaterials/   (65)      same layout, for laser output
  FactoryGenerators/(14)      built-in generators (3D Particles, GPU Particles, Text Generator, Test Pattern, Video Sampler, Depth Masker …)
  FactoryLaserGenerators/(6)
  FactorySurface2DFX/(23)     per-surface effects (Chroma Key, Pixelate, Shatter, VHS, Voronoize …) — .fs + optional .vs
  FactorySurface3DFX/(5)      FX for 3D surfaces
  FactorySurfaceLineFX/(5), FactorySurfaceLaserLineFX/(7)
  FactoryModules/   (26)      modules: main.ldat + thumbnail.png (Audio Player, Calendar Scheduler, Control Surface, DMX Router, DMX To OSC, Firmata, MIDI Out, OSC Out, Oscillator(2D/Bank), PJLink, Pollution, Weather, Timeline Scheduler …)
  SystemModules/    (2)       BPM Global, Media Playback (always present in a project, `isSystemModule`)
  Macro/main.ldat
  SampleProjects/   (6)       *.madproject folders (Video, Laser, 2 LED bar, 2 soft-edge examples)
  Guides/           (32 PDFs) offline manuals — see §6
  Translations/mm_fr.qm
  MiniMad/                    firmware zips for the MiniMad player
  Unzip/unzip.exe
```

## 3. Project file format (`.madproject` / `.mad`)

A project is a **folder** `Name.madproject`:

```
Video Example.madproject/
  Video Example.mad           116 KB — the project itself
  Media/Movies/mad_quad_1080.mov
  Media/Materials/Eye/{Eye.fs,.info,thumbnail.jpg}
  FX/Surface2DFX/Rutt Etra/{Rutt Etra.fs, Rutt Etra.vs, .info, thumbnail.jpg}
```

The `.mad` file is **binary, not XML/JSON**. Confirmed by decompiling the loader (`FUN_141324d40`, `decompiled/batch1`) and the map reader (`FUN_140bb9320`, `decompiled/batch2`):

```
int32 BE  magic        0x0BADBABE   (else "Project file is corrupted (invalid header)")
int32 BE  fileVersion  18 in the 6.1.8 samples; < 3 → silently rejected,
                       > running build's version → "created by a newer MadMapper", refused;
                       merge requires fileVersion == running version;
                       < 4 and < 13 gate legacy conversions (cueBanksV4 / cueBanks → timelineBanks)
QVariantMap           QDataStream big-endian, default stream version (no setVersion call):
                       qsizetype count (44 in the sample), then `count` × (QString key, QVariant value)
```

- `QDataStream` is used directly on an uncompressed `QFile`: no zlib, no `qUncompress`, no cipher. Custom types carry their type name inline (`QList<float>`, `MadColor`, `FilePath`); images are embedded PNG. Since the format is Qt's documented stream, a reader/writer can be built with Qt or PyQt.
- After the body, `QDataStream::status()` is checked: 1 → "File is incomplete", 2 → "File is corrupted", other → "Project file cannot be read".
- Top-level keys are consumed in this order (each handed to its own deserializer): `projectPath`, `projectSettings`, `meshes3D`, `outputs`, `visuals` (fallback `medias` + `activemedianame`), `surfaces` (+ `surfacesRelations`, per-surface `linkedS3Ds`/`linkedOutputs`), master block (`masterLevel`, `video/dmx/laserMasterColor`, `master{Video,Dmx,Laser,Audio}Level`, `masterEqSettings`, `audioInputLevel`, `engineFrozen`, `engineSpeed`, `{video,dmx,laser}OutputsFrozen`), `mediaRatio*`, `selectionGroups`, `masterCustomParameters`, `materialsInEdition`, `openedFilesInEditor`, `openedFoldersInEditor`, `timelineBanks` (or legacy `cueBanksV4`/`cueBanks`), `miniMADVideoSettings`, `miniMADLightSettings`, `madLightRecorderSettings`, `previewsData`, `resourceEditorData` (QJsonDocument), `notes`, `customColorTable`, `colorPalette`, `featuresUsageInfo`, `modules`, `mappings`, `editedVisualId`.
- Merging (File ▸ Merge) uses a per-section flag struct (surfaces, visuals, modules, timelines, outputs, meshes) and only accepts files saved by the same version.
- Warnings on load: missing 3D object file (calibration will be lost on save), laser surfaces refused without a MadLaser licence; a `silentMode` QSettings flag suppresses both.
- Versioning: release notes mention `MadMapperProjectData/` folders and MadMapper 5 → 6 conversion that "leaves the original project file untouched".

Top-level keys recovered from the sample (grouped):

| Group | Keys |
|---|---|
| Master | `masterLevel`, `masterVideoLevel`, `masterDmxLevel`, `masterLaserLevel`, `masterAudioLevel`, `masterEqSettings`, `masterCustomParameters`, `dmxMasterColor`, `laserMasterColor`, `engineSpeed`, `engineFrozen`, `dmxOutputsFrozen`, `laserOutputsFrozen`, `colorPalette`, `customColorTable`, `audioInputLevel`, `bankGenCount`, `bankIterCount` |
| Modules | `modules[]` → `moduleName`, `instanceName`, `activated`, `isSystemModule`, `attributes`, `collapsedParameterGroups`; system module attributes such as `Global BPM/BPM`, `Global BPM/Ableton Link`, `Global BPM/TAP`, `Global BPM/Midi Input` |
| Outputs | `outputs[]` → `name` (`Video-Output-1`), `outputType` (`Video`), `screenName`, `screenType`, `geometry`, `position`, `scale`, `rotation`, `flip`, `ratio`/`preserveRatio`, `frameDelay`, `enableMsaa`, `mask`, `maskOpacity`, `background`, `backgroundOpacity`, `showTestPattern`, `showDesktopWindow`, `publishNDI`, `publishSyphon`, `publishInternalLoopback`, `loopbackPixelFormat` (`PF_U8_BGRA`), `includeAlphaChannel`, `blackmagicVideoOutputConnection/Format`, `videoSnapshotFormat`, `stageSize`, `backgrounds`, `masks` |
| Surfaces | `surfaces[]` → `type` (`quad`), `name` (`Quad-1`), `surfaceId`, `visualId` (assigned media), `visible`, `locked`, `opacity`, `blendMode`, `aspectRatioMode`, `userAspectRatio`, `positions` (output corners), `positionUv`/`scaleUv`/`rotationUv`/`uvFlip` (input geometry), `isPerspective`, `geometryPrecision`, `warpingEnabled`, `feathering`, `modulation`, soft-edge: `softEdgeActive`, `softEdge{Left,Right,Top,Bottom}{Width,Curve}`, `softEdgeGamma`; FX: `FX/Active`, `FX/Name`, `FX/Timebase`, `FX/<Name>/<Param>`; `surfacesRelations`, `selectionGroups`, `previewSurfaceGroups`, `meshes3D`, `linkedS3Ds`, `linkedOutputs`, `mappings` |
| Timelines | `timelineBanks[]` (`Bank-1`), `activeTimelineBank`, `bank_id`, `bank_name`, `column_count`, `column_settings`, `conductor`, `scene`, `timeline`, `clips`, `animated`, `display_settings`, `editorSettings` (`enableSnapping`, `quantizationStr` = `1/16`, `timeEditionMode`), `timelineState` |
| Attribute registry | `attributeRegistryMap`: 64-bit id → human path → OSC path, e.g. `/Surfaces/Quad-2/Output/Soft-Edge` ↔ `/surfaces/2/soft_edge`, `/Media/Eye/Pupil Size` ↔ `/media/33/Pupil Size`. This is the bridge between UI names, OSC addresses and controls. |
| Project settings | `projectSettings` → `MidiInputSettings`, `MidiOutputSettings`, `OSCInputSettings` (`oscPort`, `oscFeedbackIp/Port`, `enableBonjour`, `bonjourNickname`), `OSCOutputSettings`, `artNet{Input,Output}InterfaceIdentifier`, `artNetOutputMaxFps/Synchro/Unicast`, `artNetRoutingTables`, `sacn*`, `sacnPriority`, `dmxInDevice/dmxOutDevice`, `ledDevicesSettings`, `ledRoutingTable`, `engineFPS`, `engineFPSMode`, `engineLinearFiltering`, `laser*` (expert mode, beam preview, security unlock), `fullscreenWhenLoadedAtStartup`, `armLasersWhenLoadedAtStartup`, `timelineStore*` |
| UI state | `editorSettings`, `*SplitViewState`, `inputPreview*`, `outputPreview*`, `rightPanelVisible`, `inspectorVisible`, `savedWindowWidth`, `projectPath`, `notes`, `openedFilesInEditor` |

Other sample projects (`index/mad_keys_diff.py` over the LED-bar, lines, soft-edge and laser examples) add these serializer facts:

- Surface `type` values seen: `quad`, `fixture` (LED), `lines` (`textured_line_chained`, `textured_line_vetical_split` [sic]), `laser_lines`, `laser_quad`; surface groups carry `isFixtureGroup`, `expanded`, `group`; 3D surfaces live in `meshes3D`/`linkedS3Ds`.
- Fixture surfaces: `fixture` → `product` (`SFX-01 RGB 1m`), `GarageCube` (manufacturer), `width`/`height`, `pixelMapping` (channel list string such as `r1 4 7 10 …`), `dmxtype`, `artnetUniverse`, `startChannel`, `avoidCrossUniversePixels`, `filtering`/`filteringMode`/`filterKernelSize`/`filterAnamorphicKernelSize`, `responsePower`, `favorite`, `isValid`, `sliders`, `perspective`/`perspectiveUv`; project-level `ArtNetInterfaces`, `autoPoll`.
- Line surfaces: `lines`, `bezierPath`/`bezier_pathes`, `hasBezier`, `bezierToNext`/`bezierToPrevious`, `bezier_linked`, `lineStyle`, `lineJoinStyle`/`join_style`, `lineAlignment`, `thickness`, `linesShrink`, `texturingMode`, `texturingVSplits`, `featheringMode`, `minIldaPoints`, `hasDynamicBoundingRect`, `Active Segment/{Start,End,Strt Smooth,End Smooth}`; line FX `FX/Animations/{Chase,Flicker,Segment Chase,Serpentine,Serp. Chained}/…` plus `Anim Mode`, `BPM Sync`.
- Laser projects: `laser_lines`, `laser_quad`, DAC settings (`30 kpps`, `127.0.0.1`), vectorization algorithm name `zhang_suen_then_guo_hall` (thinning), `mm_LastFrameData`.
- Outputs are named `projector_N` in the soft-edge examples; media tracks use `/timeline_media_tracks/<id>/<n>`; materials are addressed as `/materials/<Name>`.
- Every sample embeds the author's Mac display id (`/display/serial_number/…/Built-in Retina Display`) and hostname, so `screenName` is a hardware identity string, not a user label.

Autosave: `.autosave` suffix (`project.mad.autosave…`), interval and countdown configured in preferences; a `MadMapperProjectData/` folder is created when AutoSave or Project Backup are enabled.

## 4. Attribute / OSC model

Every controllable parameter is an **attribute** addressed by a path; the registry maps three names for each (numeric id, display path, OSC path). OSC addresses found in the binary (full list: `index/mm_osc_addresses.txt`):

- Application: `/application/preview/mode/{output,previewed,previewed_plus_output,selection}`, `/application/mad_light_recorder/{start,stop}_recording`, `/application/timeline_executor`, `/application/resource_manager`
- Master: `/master/%1`; media: `/media/{select,next,previous}`, `/media/selected/%1`; modules: `/modules/%1/{active,select}`, `/modules/select_{next,previous}`
- Timelines/cues: `/timelines/selected/by_cell/col_%1/{cue_row,scene_row}_%2/play_from_beginning`, `/timelines/selected/{columns,rows}/start_{next,previous}`, `/timelines/start_by_number`, `/conductor/{play,speed}`, `/cells/%1/%2`
- Internal event bus (also OSC-style): `/surface/{added,removed,renamed}`, `/media/{added,removed,reached_loop_end}`, `/module/{added,removed,init_called}`, `/cue_bank/*`, `/timeline_bank/*`, `/mesh/{query,loaded}`, `/camera/*`, `/syphon/*`, `/device/*`, `/mouse/*`, `/key/*`, `/gestures/*`, `/view/*`, `/editor/*`
- Services: `/io/services/{osc,midi,hid,keyboard,audioin,leapmotion,xinput,sdl2gamecontroller,ableton_link,custom}`, `/io/services/dmx/showjockey`, `/io/services/led/serial`, `/io/{artnet,sacn}_interface_registry`, `/services/io/dmx/global`, `/madam/http_server`
- Per-surface attribute paths from the sample: `/surfaces/N/{visual,color,opacity,visible,blend_mode,input_geometry,input_flip,mesh_warping,masks,soft_edge,fx,fx_active,FX/<Name>/<Param>}`; media: `/medias/N/<Param>`.

The same event/service addressing is used internally (mouse, keyboard, file dialogs), which suggests the whole app is driven by a message bus that OSC simply exposes.

## 5. Materials, FX and ISF

- Materials are **ISF** files with MadMapper extensions. Header is a JSON block in a `/*{ … }*/` comment: `CREDIT`, `DESCRIPTION`, `VSN`, `TAGS`, `INPUTS[]` (`LABEL` with `/` groups, `NAME`, `TYPE` float/bool/color/…, `MIN/MAX/DEFAULT`, `FLAGS: "button"`), and a MadMapper-specific `GENERATORS[]` (e.g. `TYPE: "time_base"` with `speed`, `reverse`, `link_speed_to_global_bpm`).
- Entry point is `vec4 materialColorForPixel(vec2 texCoord)` rather than ISF's `main()`; the engine wraps it (`Shaders/Materials/Default.vs`, `isfDefault.vs`). Standard ISF uniforms are injected: `TIME`, `CLOCK_TIME`, `DATE`, `TIMEDELTA`, `FRAMEINDEX`, `PASSINDEX`, `RENDERSIZE`, `MOUSEPOS`, `MOUSEKEYSTATE`, `isf_FragNormCoord`, plus `mm_PixelDataTex` for fixture/LED pixel data.
- ISF parsing is all in the exe (error strings: "ISF directive is not valid JSon", "Unhandled ISF input type", `INSTANCE_COUNT`, "audio and audioFFT types are only supported in GpuProgram ISF directive", "Material folder doesn't contain a fragment shader (should end with .fs)"). **ISF support is present in the Windows build** — this settles the earlier open question.
- Surface FX use the same folder layout, optionally with a vertex shader (`Rutt Etra.vs` is 5 KB: the effect is a vertex-displacement mesh).
- `.info` is a tiny XML sidecar: `<info><author/><date/></info>`.
- Each material/FX folder is self-contained and user-editable, so the built-in library is the best corpus for studying MadMapper's shader conventions.

## 5b. Modules (`main.ldat`) and the Lua runtime

From `decompiled/batch1` (`FUN_1412548d0`, `FUN_141254fb0`, `FUN_1416a90b0/9780/aaf40`, `FUN_1417d0a60`) and `decompiled/batch2` (`FUN_1405d8380`):

- A module folder is recognised by its entry script, tried in the order `main.lua`, `main.py`, `main.ldat`, `main.pydat` (first match wins). Default module sets come from `DefaultForVideoDmx.txt` / `DefaultForLaser.txt` lists.
- `main.lua` / `main.py` are read as plain text. `main.ldat` / `main.pydat` are the same scripts **encrypted with Crypto++ in CFB mode** (`CFB_DecryptionTemplate` vtable in `FUN_1405d8380`), keyed from constants inside the binary. CFB explains why the files are not block-aligned and carry no header. The factory modules, the Macro module and even the "Empty Template" ship encrypted; user-written modules can be plain `main.lua`/`main.py`. I have not extracted the key or decrypted any shipped module — that is circumventing their protection and isn't needed to study the app; the Modules guide and the in-app Code Editor show the scripting API.
- Module metadata (`credit`, `description`, `version`, `min_madmapper_version`) is parsed out of the script text header (`FUN_1407b29c0` → `FUN_1406cc9c0`, the same header scanner family used for ISF). `.info` and `thumbnail.{jpg,jpeg,png}` are read from the folder; a mtime cache avoids re-parsing.
- The same loader handles shader resources: when the resource type is not a script type it reads `.vs`/`.fs` instead (materials, FX, generators).
- Lua state (`FUN_1417d0a60`): stock Lua 5.3 (`luaL_checkversion` with `LUAL_NUMSIZES` 0x88), only base, package and math opened here (no io/os/debug), `package.path` = `!\lua\?.lua;!\lua\?\init.lua;!\?.lua;!\?\init.lua;!\..\share\lua\5.3\?.lua;…;.\?.lua;.\?\init.lua`, `package.cpath` = `!\?.dll;!\..\lib\lua\5.3\?.dll;!\loadall.dll;.\?.dll;!\?53.dll;.\?53.dll` (`!` = exe dir). The `mad` API is registered elsewhere (Python side exports `PyInit_mad`, `PyInit_nvg`, `PyInit_service`).

## 6. Offline documentation shipped with the app (`Resources/Guides/`)

Introduction to the User Interface (6.7 MB), My First Video Mapping (9.4 MB), Mesh Warping, Masking, Scenes and Cues, Modules, Control Surface Module Guide, Materials Documentation, Surface FX Documentation, Laser Materials Documentation, MadNoise, MadSDF, OSC Channels, Preferences, Space Scanner Guide, Laser Scanner Guide, Realtime Reactive Visuals, Calendar Scheduler, Cue Scheduler, Weather & Pollution Modules, Arduino Firmata, USB to LED, Stream Deck Plugin Guide, MadProjectorControl Guide, MadLaser Guide, MadLaser AVB Support, MadAI Cheat Sheet, MiniMad Controller, MINIMAD_USERGUIDE, My First MiniMad Video Export, Knowledge Base, The MadMapper FAQ.

No PDF text tool is installed on this machine (no poppler, no pypdf), so these have not been read yet.

## 7. Version history

The binary embeds release notes for every version from 6.0.0 to 6.1.8 (1,219 lines; `index/mm_release_notes.txt`), plus an old `MadMapper 2.6.0` string and a `Mar 01 2017` date from a bundled library. Useful for a feature timeline.

## 8. Ghidra workflow (persistent project)

- Ghidra 12.1.4 at `E:\Claude\ghidra\ghidra_12.1.4_PUBLIC`, JDK 21 at `C:\Program Files\Eclipse Adoptium\jdk-21.0.12.101-hotspot`.
- Analyzed project: `ghidra\MadMapper.rep` (full auto-analysis, 1476 s, 105,415 functions, 2,234 named).
- `ghidra\scripts\ExportIndex.java` → `index\functions.csv`, `index\strings.csv` (string → referencing functions), `index\magic_refs.txt`.
- `ghidra\scripts\DecompileMatching.java <outdir> <regex | addr+addr+…> [max=N]` → one `.c` per function in `decompiled\batchN\`. Headless splits script args on commas, hence `+`.
- Run pattern: `analyzeHeadless <projdir> MadMapper -process MadMapperDemo.exe -noanalysis -readOnly -scriptPath ghidra\scripts -postScript <Script>.java <args>`.
- REA (MCP) can also use Ghidra but re-analyzes into a throwaway project on every session; `REA_GHIDRA_STARTUP_TIMEOUT_MS` is set to 3,600,000 in the MCP config for that.

## 9. What is still unknown

- Which block cipher/key length Crypto++ CFB uses for `.ldat` (deliberately not pursued).
- The per-surface-type, per-output-type and per-media-type key schemas (batch 2 decompiles in progress).
- The ISF header grammar as implemented (batch 1 `FUN_1406cd780`, analysis in progress).
- The `MadamScripting.dat` Qt resource bundle contents (fonts seen; may hold the scripting editor's JS/QML).
