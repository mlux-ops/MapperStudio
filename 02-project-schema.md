# MadMapper 6.1.8 — `.mad` project schema (from decompiled deserializers)

Source: `decompiled/batch2` (Ghidra output of the functions the top-level loader calls; see `01-binary-and-file-formats.md` §3 for the header and top-level key order). Helper calls in the decompile: `FUN_140684640(map, key)` = get, `FUN_140b37650(map, key)` = contains, `FUN_140692930` / `FUN_140a644a0` = get-with-default. "version" below is the file version read from the header (global `DAT_142a87348`; 18 in the shipped samples).

## surfaces — `FUN_14158f890` (QVariantList of QVariantMap)

Only `type` (QString) is read here; the rest of each map goes to the type's own loader (`vtable+0x158`). Unknown or empty type → silently skipped; a loader returning 0 → log "Error parsing surface of type %s" and the object is deleted.

| `type` string | object size | constructor | notes |
|---|---|---|---|
| `quad` | 0x14e8 | `FUN_14156fbf0` | base video surface |
| `triangle` | 0x298 | `FUN_14164ef90` | |
| `circle` | 0x14e8 | `FUN_1412af7e0` | same size as quad → shares the quad base |
| `polygon` | 0x260 | `FUN_141501040` | |
| `mask` | 0x1520 | `FUN_14146d0a0` | |
| `lines` | 0x1540 | `FUN_1413eceb0` | textured lines (Bezier, chained) |
| `group` | 0x250 | `FUN_1415d2660` | surface group; `isFixtureGroup` key seen in samples |
| `surface3D` | 0x8b8 | `FUN_141593310` | OBJ-based 3D surface |
| `laser_surface3D` | 0xc40 | `FUN_14109d7f0` | |
| `laser_lines` | 0x19e8 | `FUN_141360080` | |
| `laser_text` | 0x1a18 | `FUN_141367950` | |
| `laser_quad` | 0x1850 | `FUN_141112f40` | |
| `laser_circle` | 0x1850 | `FUN_1412b0e60` | |
| `fixture` | 0x1e0 | `FUN_14135bf20` | LED fixture (pixel-mapped) |
| `fixtureline` | 0x1e0 | `FUN_141375ea0` | |
| `fixturecircle` | 0x1f0 | `FUN_1410d7060` | |
| `fixturebezier` | 0x1668 | `FUN_1413763c0` | |

Per-type keys seen in the samples (not yet decompiled): quad → `name`, `surfaceId`, `visualId`, `visible`, `locked`, `opacity`, `blendMode`, `aspectRatioMode`, `userAspectRatio`, `positions`, `positionUv`/`scaleUv`/`rotationUv`/`uvFlip`, `isPerspective`, `geometryPrecision`, `warpingEnabled`, `feathering`, `modulation`, `softEdge*`, `FX/*`; fixture → `fixture{product, GarageCube, width, height, pixelMapping, dmxtype, artnetUniverse, startChannel, …}`; lines → `lines`, `bezierPath`, `lineStyle`, `lineJoinStyle`, `thickness`, …

## outputs — `FUN_1414d2c80`

- `outputs` (list) → per item `outputType` (QString, default `"Video"`):
  - `Video` → 0x458-byte object (`FUN_1411a79e0`); default name `Video-Output-N` or `Video-Buffer-N`; `id` -1 means "allocate", then de-duplicated; internal kind 2 = laser buffer (used by `/camera/loopback/{video|laser}`).
  - `DMX` → 0x2f8 (`FUN_14109b9c0`).
  - `Laser` → 0x620 (`FUN_1410faf00`), only when the MadLaser capability flag `DAT_142a51b82` is set; otherwise "Laser not supported in this version".
  - anything else → "unknown output type: %s", skipped.
- `backgrounds`, `masks` (lists, optional) → `FUN_1414d2a20`.
- No version gates. Output keys seen in samples: `name`, `screenName`, `screenType`, `geometry`, `position`, `scale`, `rotation`, `flip`, `ratio`, `preserveRatio`, `frameDelay`, `enableMsaa`, `mask`, `maskOpacity`, `background`, `backgroundOpacity`, `showTestPattern`, `showDesktopWindow`, `publishNDI`, `publishSyphon`, `publishInternalLoopback`, `loopbackPixelFormat`, `includeAlphaChannel`, `blackmagicVideoOutput{Connection,Format}`, `videoSnapshotFormat`, `stageSize`, `locked`, `active`, `manuallySetup`, `customSettings`.

## projectSettings — `FUN_141205720`

| key | type | default |
|---|---|---|
| `id` | int | -1 → random 1..2³¹ |
| `fullscreenWhenLoadedAtStartup` | bool | false |
| `armLasersWhenLoadedAtStartup` | bool | false |
| `loadMasterSettings` | bool | false |
| `MidiInputSettings` | map | `useMidiNoteVelocity` bool false; `MidiInputList[]` → `uniqueId` int 0, `name`, `deviceName`, `active` bool false, `feedbackDeviceName` |
| `MidiOutputSettings` | map | `MidiOutputList[]` → `uniqueId`, `name`, `deviceName` |
| `OSCInputSettings` | map | `bonjourNickname` "MadMapper", `oscPort` **8010**, `enableBonjour` true, `oscFeedbackIp` "192.168.1.1", `oscFeedbackPort` 9000 |
| `OSCOutputSettings` | map | `OSCOutputList[]` → `uniqueId`, `name`, `nickname`, `ipAddress`, `port` int 0 |
| `engineFPSMode` | int | 0 |
| `engineFPS` | float | built-in constant |
| `engineLinearFiltering` | bool | true |
| `enableHardwareAccelerationOption` | bool | false |
| `laserExpertMode` | bool | false |
| `laserUnlockSecurityFeatures` | bool | false |
| `laserMaxBeamIntensity` | double | |
| `laserVisualizationEnabled` | bool | false |
| `laserVisualizationSoftware` | str | "Capture" |
| `laserBeamPreviewLevel` | double | |
| `laserBeamPreviewOrigin` | QPointF | (0,0) |
| `laserBeamPreviewEndOnPath` | bool | false |
| `laserBeamPreviewEnableSmog` | bool | true |
| `timelineStopTimelinesOnBankSwitch` | bool | true |
| `timelineStoreFixturesInScenes` | bool | true |
| `timelineStoreSurfaceOutputGeometry` | bool | true |

Art-Net/sACN/DMX/LED keys seen in samples (`artNet*`, `sacn*`, `dmxInDevice`, `dmxOutDevice`, `ledDevicesSettings`, `ledRoutingTable`, `interfacesAutoPoll`) are read by a callee not yet decompiled.

## visuals — `FUN_141659f30` (media bin)

- `visuals` (list). Per item: `url` (str), `instanceName` (str), `isGenerator` bool, `isLaserGenerator` bool, `moduleName` (str), legacy `modules` list.
- URL namespaces: `/madam/<instance>/…` (module-driven), `/texture/<instance>/…`, `/generator/<moduleName>` (`_Legacy4` suffix stripped), `/laser_generator/<moduleName>`, `/camera/loopback`. Movie/image/folder/Spout/NDI/capture kinds are decided by `FUN_141665620` (not yet decompiled). Visual kind enum values seen: 2, 3 (laser-only), 5 (never loads), 10 (loopback).
- version < 13: URLs must start with `/madam/` or `/texture/` and are rewritten with the instance name.
- Unloadable visual → warning "Failed loading visual with url … Unsupported media type"; unless `silentMode`, a dialog warns that the media **will be erased from the project on save**.
- Missing files are collected and passed to a relink pass (`FUN_141661cc0`).
- Legacy `medias` (`FUN_141659cd0`): lists `images`, `movies`, `quartz`; built-in test patterns `:4x4.png` … `:16x16.png` are registered first.

## modules — `FUN_141688e70`

- `modules` (list). Items with `isGenerator`/`isLaserGenerator` true are skipped here (they are visuals). Others → 0x188-byte module instance, loaded by `FUN_1416a00b0` (keys seen in samples: `moduleName`, `instanceName`, `activated`, `isSystemModule`, `attributes`, `collapsedParameterGroups`).

## timelineBanks — `FUN_140cb4a30`

- `timelineBanks` (list) → bank object (`FUN_140c912a0`), loaded by `FUN_140c9c210`:

| key | type | default / rule |
|---|---|---|
| `bank_id` | int | 0; re-issued on load |
| `bank_name` | str | ""; made unique on collision |
| `row_count` | int | 33 |
| `column_count` | int | 16 |
| `scene_row_count` | int | 0 |
| `grid_settings` (fallback `view_settings`) | map | four ints (`FUN_140ca33a0`) |
| `timelines` | list | one cell map per row×col (`uid` int, generated if missing) → `FUN_140c8dcd0` (clips/cues/markers live here) |
| `conductor` | map | conductor timeline; duplicate unique id → "Project file is corrupted. Conductor unique ID is in use." |
| `column_settings` / `row_settings` | lists | resized to columns / rows |
| `attributeRegistryMap` | map | read and discarded at this level |
- `activeTimelineBank` (str) → activated after load.
- `editorSettings` (map) → `FUN_140d65ae0` (keys seen: `enableSnapping`, `headerMode`, `quantizationStr`, `restartPlaybackFromTimeMarker`, `timeEditionMode`).

## mappings — `FUN_140a61030` (controls table)

- Flat list of alternating `[QString controlPath, QVariantMap record]`. Record (`FUN_140a5f670`):

| key | type | default |
|---|---|---|
| `enabled` | bool | true |
| `channel` | str | — ; a control-channel path resolved via the global channel manager (preferred when present) |
| `channelInfos` | map | — ; the input source description (MIDI/OSC/DMX/keyboard device, note/cc/address…) parsed by `FUN_140a5d9d0` |
| `sourceMin` / `sourceMax` | double | 0 / 1 |
| `targetMin` / `targetMax` | double | 0 / 1 |
| `toggle` | bool | false |
| `circular` | bool | false |
| `sensitivity` | double | 1 |
| `filterSettings` | map | `FUN_140a5ee90` (smoothing) |
| `curveSettings` | map | `FUN_140a5e330` (response curve) |
| `feedback` | bool | true (send value back to the controller) |
- Paths are resolved against the control-node registry; unresolved paths are kept and warned: "Error restoring mapping table: control node %s is not present".
- Backward-compat rewrites when a path is missing: strip `/parameters`; `fixture_luminosity`→`luminosity`; `fixture_response`→`response`; `/fixtures`↔`/surfaces`; `/fx`→`/parameters`; `/laser_surfaces/`↔`/surfaces/`; `/color`→`/color/rgba`; `/red|green|blue`→`/color/<x>`. Regexes normalise `/scenes/by_cell/col_N`, `/cues/by_cell/col_N/row_M`, `/scenes/by_name/…`, `/cues/by_name/…`.
- version < 13: cell-scene paths get `/scene_row_1` + `/play_from_beginning`; version < 19: `/medias/` and `/by_cell/` resolution enabled.

## meshes3D — `FUN_141320ef0`

List of maps, each a `Mesh3DFilePath` (`FUN_1414c19f0`), validated and inserted into a `QAbstractItemModel`; invalid entries dropped silently.

## masterEqSettings — `FUN_141302540` / `FUN_14080fba0`

A setter mirrored to `QSettings("masterEqSettings")`. The map has keys `"0"`…`"3"` (four EQ bands, inactive bands omitted), each `{type, freq, gain, q}`; `type` names come from a global id→name table.

## Common visual fields — `FUN_141665620`

Every visual reads `xFlip`, `yFlip` (bool, false) and optional `audioRouting` (map → `FUN_140808000`), then instantiates its media through factory `FUN_14063e530` by internal kind (4–8 → factory ids 5, 6, 0, 1, 4). The url-to-kind decision sits in the callers / the factory (batch 5).

## Output backgrounds — `FUN_1414d2a20`

List of maps, each a `BackgroundFilePath` with `preserveRatio` (bool, false).

## Surface loaders in detail (batches 5 and 7)

All concrete surfaces first call the **base surface loader `FUN_14158a240`**:

| key | type | default | notes |
|---|---|---|---|
| `name` | str | "" | |
| `surfaceId` | int | −1 | |
| `visualId` | int | −1 | links to `visuals[].id`; −1 → the "no media" placeholder visual |
| `visible` / `locked` / `previewed` | bool | true / false / false | |
| `uvFlip` | uint | 0 | |
| `blendMode` | uint | 2 | |
| `opacity` | double | 1.0 | |
| `feathering` | double | 0.0 | |
| `geometryPrecision` | double | 0.5 | |
| `modulation` | colour (RGBA or HSVA) | — | |
| `uvs` | QByteArray (`QPolygonF`) | — | input-geometry polygon; parse failure fails the load |
| `position` (QPointF), `rotation` (double 0), `scale` (double 1) | | | output transform; for file version ≤ 15 on legacy surfaces these come from `positionUv`/`rotationUv`/`scaleUv` instead |
| `positionUv` (QPointF), `rotationUv` (double 0), `scaleUv` (double 1, clamped ≥ 1e-9) | | | input transform |
| `customSettings` | map | {} | **holds the FX keys** (see below) |
| `collapsedParameterGroups` | map | {} | inspector UI state |

**FX are stored inside `customSettings`**, not at the surface top level: `FX/Active` (bool), `FX/Name` (string, e.g. `Rutt Etra`, `Color Controls`), `FX/<Name>/<Param>` (the FX's ISF inputs), `FX/Timebase`. Files older than version 9 are migrated from `Shader` / `FX` / `fx/FX Type` to that layout (`Default` → `Color Controls`, inactive); files older than 18 get `/medias/` → `/media/` rewritten in string values.

The Quad **writer** (`FUN_1415803e0`) always writes `type`, `positions`, `isPerspective`, `aspectRatioMode`, `userAspectRatio`, the soft-edge block and `masks` (a list); the `warping_*` keys only when warping is enabled (Bezier link keys only when `warping_bezier`). Blobs are `QDataStream` big-endian, stream version 12; `positions` is a standard Qt `QPolygonF` (uint32 count, then double x, double y).

**Quad** (`FUN_141575410`; also circle, and the base for lines) — no version gate:

| key | type | default / rule |
|---|---|---|
| `isPerspective` | bool | true |
| `positions` | QByteArray (serialised `QPolygonF`, the 4 output corners) | required; unparseable → load fails |
| `warpingEnabled` | bool | false |
| `warping_size` | QSize | grid columns × rows |
| `warping_subdivisionlevel` | int | required when warping |
| `warping_positions`, `warping_uvs` | QByteArray (grid blobs, `FUN_14156be00`) | required when warping |
| `warping_bezier` | bool | false |
| `warping_bezierHorizontalLinks`, `warping_bezierVerticalLinks` | QByteArray | optional; absent → empty (w+1)(h+1) grid |
| `showUvGrid`, `showMeshGrid` | bool | false |
| `inputOutputLinked` | bool | true |
| `maskEnabled` | bool | false; when the key is absent the legacy `masks` list is used |
| `mask` | map | `positions` (QByteArray polygon, required), `polygonInverted` (bool false) |
| `maskAttachedTo` | int | optional (Nothing / Quad / Input per the Masking guide) |
| `aspectRatioMode` | int | optional; `userAspectRatio` (QPointF, (0,0)) read only inside this branch |
| `softEdgeActive` | bool | false |
| `softEdge{Left,Top,Right,Bottom}Width` | float | 0 |
| `softEdge{Left,Top,Right,Bottom}Curve` | float | 0.5 |
| `softEdgeGamma` | float | 1.8 |

**LineContainer** (`FUN_1413edf30`): file version > 6 → Quad loader, then `texturingMode` (string: `white`→0, `textured_match_position`→1, `textured_line`→2, `textured_line_chained`→3, `textured_line_vetical_split` [sic]→4, other→3), `texturingVSplits` (int, 10, only with texturingMode), `linesShrink` (double, 0), `hasDynamicBoundingRect` (bool, true); the line paths themselves come from `bezierPath` children (`FUN_141145d50`, batch 7). Version ≤ 6: legacy `positions` + `line` list of 2-point segments.

**FixtureQuad** (`FUN_14135d630`): `positions` (QByteArray) and, for file version < 16, `uvs`. The fixture base `FUN_14135c3d0` reads:

| key | type | default | notes |
|---|---|---|---|
| `fixture` | map | — | fixture definition (`FUN_14137b580`; contains the product/pixel-mapping data seen in samples: `product`, `GarageCube`, `width`, `height`, `pixelMapping` "r1 4 7 10 …", `dmxtype`, `isValid`, `favorite`) |
| `manufacturer`, `product` | str | "" | legacy, only without a `fixture` map |
| `artnetUniverse` | int | 0 | |
| `startChannel` | int | 0 | |
| `filteringMode` | int | 0 | if absent, legacy `filtering` (bool false) |
| `filterAnamorphicKernelSize` | QSize | (8,8) | |
| `filterKernelSize` | int | 8 | |
| `responsePower` | float | — | optional |
| `ledStripSize` / `matrixSize` | QSize | invalid | same field, first present wins |
| `sliders` | map | — | fixture slider values |

**Surface3D** (`FUN_141599530`):

| key | type | default / rule |
|---|---|---|
| `renderMode` | int | bit 0 wireframe, bit 3 lighting (legacy); else `wireframeEnabled`, `lightingEnabled` (bool false) |
| `faceCullingMode` | int | 0 |
| `texturingMode` | int | 0 (int here, string for lines) |
| `textureWrappingMode` | int | 0 |
| `texturingRotation` | vec3 | — |
| `texturingSmoothness` | double | 0 |
| `meshPath` | map | the OBJ reference (`Mesh3DFilePath`) |
| `rotation3D` (quaternion) or `rotation3DEuler` (vec3) | | first present wins |
| `3D2DLinks` | list of `{meshID, vertexID, 2D point}` | the calibration correspondences |
| `transformMode` | int | optional |
| `lights` | list of maps | each a `Surface3DLight` (`FUN_14159bbd0`) |
| `shininess` | float | optional |
| `ambientColor`, `specularColor`, `wireframeColor`, `textureColor` | color | optional |
| `meshModifications`, `uvsModifications` | custom metatypes | optional (`Surface3D::MeshModifications` / `UvsModifications`) |
| `originUvs` | QByteArray polygon | optional; parse failure fails the load |

## Output loaders in detail

Both outputs first call the **base output loader `FUN_1414c4d70`**: `id` (int −1), `name` (str), `buffer` (bool false — a Video Buffer rather than a physical output), `position` (QPointF), `stageSize` (QSizeF), `rotation` (double 0), `scale` (double), `active` (bool), `locked` (bool), `publishInternalLoopback` (bool), `showTestPattern` (bool), `background` (list → `FUN_1414c41e0`) + `backgroundOpacity` (float), `mask` (list, same parser) + `maskOpacity` (float), `ratio` (QSizeF), `preserveRatio` (bool), `flip` (QSize), `customSettings`, `collapsedParameterGroups`. Files older than version 5 have `position`/`stageSize` normalised from an 800×600 reference stage.

**VideoOutput** (`FUN_1411aa580`): `screenType` (int 0), `screenName` (str; `"/<digits> "` normalised to `"/"`), `manuallySetup` (bool), `geometry` (QRect), `dgeometry` (QRect, optional), `frameDelay` (int 0), `publishSyphon` / `publishNDI` (bool false), `NDIIncludeAlphaChannel` (fallback `includeAlphaChannel`, bool false), `loopbackPixelFormat` (str, `PF_U8_BGRA`, 48-entry pixel-format table), `enableMsaa` (bool true), `showDesktopWindow` (bool false), `blackmagicVideoOutputFormat` / `blackmagicVideoOutputConnection` (str), `videoSnapshotFormat` (**int**, 0).

**DmxOutput** (`FUN_14109bd40`): `customDefinitionEnabled` (bool false), `customDefinition` (QSize 1920×1080). Universe/device routing lives in project settings and fixtures, not on the output.

## Mapping source (`channelInfos`, `FUN_140a5d9d0`)

`url` (str), `name` (str), `path` (str), `device` (map → `FUN_140a605a0`: `ct` (int, the device/channel-type discriminator; value table not resolved), `url`, `name`, `path`). The concrete source (MIDI note/CC, OSC address, Art-Net channel, key, gamepad axis) is therefore encoded in the **path strings** of the control-channel tree (`/io/services/midi/...`, `/io/services/osc/...`), consistent with the error "Invalid MIDI channel name %s, missing midi channel/…" (`FUN_1409e2500`).

## Visual records (`visuals[]`, `FUN_1410c3bf0`)

| key | type | default |
|---|---|---|
| `id` | int | −1 (the id surfaces reference via `visualId`) |
| `url` | str | "" (`/materials/<Name>`, `/generator/<Module>`, `/laser_materials/…`, `/spout/<name>`, `/camera/…`, or a file path) |
| `type` | str | category: Generators, Materials, Laser Materials, Quartz Composer, Images, Movies, Image Folders, Spout (Syphon), Live Inputs, Laser Generators, Montages, ISFs, Testcards |
| `mmtype` | str | kind: Movie, Image, Live, Syphon, Spout, Quartz, Generator, Material, TimelineMediaTrack, LaserMaterial, ISF |
| `name` | str | "" |
| `syphonAppName` | str | "" (Syphon visuals are converted to Spout `/spout/<name>` on Windows) |
| `attributes` | map | the media's parameter values (ISF inputs, playback settings); `/medias/`→`/media/` rewritten for old files |
| `collapsedParameterGroups` | map | {} |
| `gridPos` | int | 0 (position in the media bin grid) |
| `instanceThumbnail` | QImage | — , `instanceThumbnailId` int |

Legacy rewrites (file version < 18): `/vector_materials/`→`/laser_materials/`, `VectorMaterial`→`LaserMaterial`, `/madam/`/`/texture/` generator URLs → `/generator/<name>`, material URLs collapsed to `/<seg1>/<seg3>`, V3 materials relinked.

## Timeline content (`timeline` map of a cell, `FUN_140d66210`)

`name` (str), `animated` (bool true), `comment` (str), `color` (QColor), `clips` (list → `FUN_140d5c170`), `tracks` (list), `markers` (list), `transition_settings` (map), `display_settings` (`timeRangeLeft`, `pixelDuration`, `viewVerticalOffset`, `viewVerticalZoom`, `signatureNum`, `signatureDen`, `trackDisplaySettings`, `audioTrackDisplaySettings`, `audioTrackForBackground`, `trackOrderPerType`, `collapsedNodes`), `loop_settings` (`enabled`, `start`), `playback_settings` (`speed` = FixedSpeed | ControlledSpeed, `ExtSync`, `ArtNet`, `syncSource`, `syncSourceDeviceName`, `ltcChannelNumber`, `ltcFramesPerSecond`, `timeCodeOffset`), `launch_settings` (`quantizeNum`, `quantizeDen`).

Cue export / clipboard layout (`FUN_140cf1fc0`, a writer): `timeOffset`, `duration`, `sourceSelectionMode`, `timelineId`, `animated`, `tracks` {trackId → `{type, attrUrl, content[]}`}, `tracksOrder` [{idx, trackId}], `tracksClips`, `timelineClips` {name → {trackId, timelineId, trackAttrUrl}}, plus `controls` and `markers` for whole-timeline copies. Clip keys (`media`, `timeline`, `clipClass`, …) are in `FUN_140d5c170` / `FUN_140d6c370` (not decompiled).

## Line paths (`bezierPath` children, writer `FUN_141145d50`)

Each path: `enabled` (bool), `name` (str), `bezierPath` (list of points, each `{<point>, hasBezier, bezierToPrevious, bezierToNext}`), `feathering` (double), `featheringMode` (int), `rotation` (double).

## Timeline cells (`FUN_140c8dcd0`) and grid settings (`FUN_140ca33a0`)

Cell: `uid` (int; generated when 0), `name` (str), `pixmap` (+ `pixmapId`, thumbnail), `scene` (bool: this cell is a scene), `exportSettings` (map), `timeline` (map → `FUN_140d66210`, batch 7: `clips`, `markers`, `tracks`, `color`, `comment`, `animated`, `transition_settings`, `display_settings`, `loop_settings`, `playback_settings`, `launch_settings`).
Row/column setting item (`FUN_140ca3120`): `name` (str), `disabled` (bool).
Grid settings: `exclusivityMode` (`Horizontal`, `Vertical`, `None`, `Grid`), `viewMode` (`Conductor`, `Grid`, `ConductorAndGrid`), `cellSize` (int), `liveMode` (bool).

## Visual file resources (`FUN_14063e530`)

Not a kind classifier: given a resolved file path it reuses an existing `MadFileResource` from the `MadResourceRegistry` or creates one (`FUN_14063baf0`); relative (`./`) or missing paths return null with a log line. Kind names present in the binary: Movie, Image, Quartz, Generator, Camera, Syphon, Spout, Shader, Capture, Video, Folder; camera URL namespaces `/camera/{ndi,blackmagic,kinect,sony,canon,ponk,DirectShow,mf}`. URL dispatch is `FUN_1410c3bf0` (batch 7).

## C++ class ↔ surface type (resolved from MSVC RTTI)

| type | class | load method (vtable +0x158) |
|---|---|---|
| quad / circle | `Quad` | `FUN_141575410` (reads `maskAttachedTo`, `isPerspective`, `warping_*`, `showUvGrid`, `softEdge*`) |
| lines | `LineContainer` (derives from Quad) | `FUN_1413edf30` (`texturingMode`, `texturingVSplits`, `textured_*`) |
| fixture | `FixtureQuad` (+`FixtureIntf`) | `FUN_14135d630` (unconfirmed) |
| surface3D | `Surface3D` (+`Mesh3DFilePath`, `Surface3DLight`) | `FUN_141599530` (`texturingMode`, `wireframeEnabled`, `lightingEnabled`, `faceCullingMode`, `textureWrappingMode`, `shininess`) |
| Video output | `VideoOutput` | `FUN_1411aa580` (vtable +0xa8; `screenType`, `screenName`, `manuallySetup`, `geometry`, `frameDelay`, `publishSyphon`) |
| DMX output | `DmxOutput` | `FUN_14109bd40` (`customDefinitionEnabled`, `customDefinition`) |

Note: `lineTexturingMode` / `lineTexturingVSplits` are `QSettings` preferences, not project keys.

## Not decompiled (diminishing returns)

Fixture definition map (`FUN_14137b580`), clip/marker keys (`FUN_140d5c170`, `FUN_140d6c370`, `FUN_140d69060`), the `ct` device-type values, the warp-grid blob element layout (`FUN_14156d710`), the output writer, the module instance `attributes` map, and the per-media `attributes` keys. All of these can be recovered from a saved project with `index\mad_keys.py` once a licence allows saving, which is cheaper than further decompilation.
