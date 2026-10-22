# MadMapper 6.1.8 — attributes, OSC addresses and the controls table

Sources: `Resources\Guides\OSC Channels.pdf` (written for MadMapper 4; the address scheme still holds in 6 with the changes noted), docs page *OSC Commands & Channels List* (v6), the 124 OSC literals in the binary (`index\mm_osc_addresses.txt`), the `attributeRegistryMap` in the sample projects, and the decompiled mapping loader (`02-project-schema.md`).

## 1. Model

Every parameter in MadMapper is an **attribute** living in a tree of control nodes. Each attribute has:

- a display path (`/Surfaces/Quad-2/Output/Soft-Edge`, `/Media/Eye/Pupil Size`), used by the inspector and the Controls dialog;
- an OSC path (`/surfaces/2/soft_edge`, `/media/33/Pupil Size`), lower-case, with numeric ids for surfaces and media, or the name/group path when addressed from outside (`/surfaces/Group-1/Quad-1/opacity`);
- a 64-bit registry id, stored in the project's `attributeRegistryMap` (id → display path → OSC path) so that mappings survive renames.

OSC reaches an attribute directly (predefined address, no range/filter settings) or through the **controls table** (`mappings` in the project): a `channelInfos` source (MIDI / OSC / DMX / keyboard / gamepad / module output such as an Oscillator) mapped onto the attribute with `sourceMin/Max`, `targetMin/Max`, `toggle`, `circular`, `sensitivity`, a filter and a curve, with optional `feedback` to the controller. The same bus carries internal events (`/surface/added`, `/media/reached_loop_end`, `/mouse/down`, `/key/up`, `/file_dialog/open` …), so OSC is a window onto the app's own message system.

Predefined addresses are discovered by right-click → *Copy OSC address*, from the Controls dialog's `+` tree (Edit ▸ Controls List), or via **OSCQuery** (`/madam/http_server`; Bonjour nickname defaults to "MadMapper"). Project defaults: OSC input port **8010**, feedback 192.168.1.1:9000 (`projectSettings`); the v6 docs mention 8000 as the usual input port, so check Preferences ▸ OSC/MIDI.

Types: BOOL, FLOAT, INT, STRING, nil (trigger), RGBA colour. `*` wildcards address several parameters at once.

## 2. Address families

| family | examples |
|---|---|
| Surfaces `/surfaces/[selected \| path]/…` | `visible`, `opacity` 0–1, `visual/{type,number,name}`, `output/{x,y}` −2…2, `output/scale` 0–10, `output/rot` 0–360, `output/handles/[0-3]/{x,y}`, `input/{x,y,scale,rot,flip}` (flip: No/X/Y/XY), `invert_mask`, `blend_mode` 0–6, `color/{red,green,blue,rgba,hue,saturation,value}`, `luminosity`, `response`; 3D: `output/3d_rot_{x,y,z}`, `color/ambient/*`, `lights/0/{distance,latitude,longitude,pos_x,pos_y,pos_z,red,green,blue,color}`; v6 adds `soft_edge`, `mesh_warping`, `masks`, `input_geometry`, `output_geometry`, `input_flip`, `fx`, `fx_active`, `FX/<Name>/<Param>`, `lines`, `lines_shrink`, `Active Segment/*` |
| Fixtures `/fixtures/[selected \| path]/…` | `visible`, `luminosity`, `response` 1–4, `visual/*`, `color/*`, `input/*`, `sliders/[n]` |
| Media `/medias/…` (`/media/…` in v6 literals) | `select` 0–255, `next`, `previous`, `per_type_selection/{next,previous}_[type]`, `[name]/select`, `assign`, `assign_to_all_surfaces`, `restart`, `play_forward`, `pause`, `play_backward`, `begin`, `loop`, `position` 0–1, `position_sec`, `position_frame`, `previous_frame`, `next_frame`, `play_speed` 0–4, `absolute_speed` −4…4, `loop_start`, `loop_end`, `audio_level` 0–4, plus every ISF input of a material (`/media/33/Pupil Size`) |
| Cues (v4/5) `/cues/…` → Timelines (v6) `/timelines/…` | v4: `/cues/active_bank`, `/cues/[bank]/columns/{start_next,start_previous,select_next,select_previous,start_selected,start_by_number,[column]}`, `/cues/[bank]/scenes/by_name/[name]`, `…/scenes/by_cell/col_N`, `…/cues/by_name/[name]`, `…/cues/by_cell/col_N/row_M`, `…/cues/{start_next,…,start_by_number}`. v6: `/timelines/selected/by_cell/col_N/{scene_row_M,cue_row_M}/play_from_beginning`, `/timelines/selected/{columns,rows}/start_{next,previous}`, `/timelines/start_by_number`, `/conductor/{play,speed}`, `/cells/N/M`. The project loader rewrites old paths (`/scene_row_1`, `/play_from_beginning`, `/medias/`→`/media/`) when it meets file versions < 13 / < 19. |
| Master `/master/…` | `master_level`, `master_video_level`, `master_dmx_level`, `master_audio_level`, `audio_input_level` 0–4, `video_color/*`, `freeze_engine`, `engine_speed` 0–2, `reset_engine_speed`, `freeze_video_output`, `freeze_dmx_output`, `output_cursor`, `output_cursor_size`, `test_pattern`; v6 adds `master_laser_level`, `Global_BPM/{BPM,TAP,Beat,Resync,Ableton Link,…}` |
| Modules `/modules/…` | `select` 0–255, `select_by_name`, `select_next`, `select_previous`, `[name]/select`, `[name]/active`, `[name]/<module parameters>` (e.g. Oscillator: signal, timing, speed, phase, range, value) |
| Outputs `/outputs/[name]/…` | `enabled`, `show_desktop_window`, `show_test_pattern`, `publish_to_syphon_spout`, `publish_to_ndi` |
| Application `/application/…` | `mad_light_recorder/{start,stop}_recording`, `preview/active_preview_group`, `preview/preview_groups/[name]`, `preview/mode/{output,previewed,previewed_plus_output,selection}`, `medias/add` (file URL), `medias/remove` (name), `view/fullscreen`, `timeline_executor`, `resource_manager` |
| Internal services (not for users, visible in the binary) | `/io/services/{osc,midi,hid,keyboard,audioin,leapmotion,xinput,sdl2gamecontroller,ableton_link,custom}`, `/io/services/dmx/showjockey`, `/io/services/led/serial`, `/io/{artnet,sacn}_interface_registry`, `/services/io/dmx/global`, `/camera/loopback/{video,laser}`, `/editor/*`, `/console/*` |

## 3. Other control inputs

- **MIDI**: class-compliant devices auto-detected; Note, CC, 14-bit pitch bend; optional feedback device (motor faders, LED buttons). `MidiInputSettings.useMidiNoteVelocity` decides whether note velocity becomes the value.
- **DMX in** (Art-Net / sACN / USB), **keyboard**, **gamepad** (SDL2 / XInput), **Leap Motion**, **Ableton Link** (BPM), **Stream Deck** (via the HTTP server; see *Stream Deck Plugin Guide*), **PJLink** (projector power/input via MadProjectorControl).
- Outgoing: *OSC Out* and *MIDI Out* modules send values or cue-driven packets (MIDI Out needs loopMIDI on Windows).

## 4. Rename-safe path rewriting (from `FUN_140a61030`)

When a stored mapping path no longer resolves, the loader tries: strip `/parameters`; `fixture_luminosity`→`luminosity`; `fixture_response`→`response`; `/fixtures`↔`/surfaces`; `/fx`→`/parameters`; `/laser_surfaces/`↔`/surfaces/`; `/color`→`/color/rgba`; `/red|green|blue`→`/color/<x>`; and regex normalisation of `/scenes/by_cell/col_N`, `/cues/by_cell/col_N/row_M`, `/scenes/by_name/…`, `/cues/by_name/…`. Unresolvable paths are kept with a warning ("control node %s is not present") so a later rename can restore them.
