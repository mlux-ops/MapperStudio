"""The main window: menus, views, panels, the render timer and undo."""
from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QAction, QKeySequence, QGuiApplication, QScreen, QCloseEvent
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QDockWidget, QFileDialog, QMessageBox, QTabWidget, QLabel, QVBoxLayout,
    QInputDialog, QApplication,
)

from ..model import Project, QuadSurface, Output, Visual, VisualKind, Shape, new_default_project, save_project, load_project, ProjectError
from ..model.mad_import import import_mad_project
from ..madfile import MadFileError
from ..render import RenderEngine, ViewRect
from ..render.gl import make_fbo
from ..render.geometry import bilinear_grid
from .gl_views import StageView, InputView, OutputWindow
from .panels import SurfacesPanel, OutputsPanel, MediaPanel, Inspector, OscPanel
from ..osc.server import OscServer
from ..osc.tree import OscTree
from ..osc.protocol import OscMessage

UNDO_LIMIT = 100


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MapStudio")
        self.resize(1500, 900)
        self.project = new_default_project()
        self.engine = RenderEngine(self.project)
        self.output_windows: dict[int, OutputWindow] = {}
        self._closing_windows: list[OutputWindow] = []   # closed windows kept alive until the next tick
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self._dirty = False
        self.quiet = False   # screenshot / scripted mode: no modal dialogs

        # central: input view | stage view
        self.stage = StageView(self.engine)
        self.input_view = InputView(self.engine)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.input_view)
        split.addWidget(self.stage)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        self.setCentralWidget(split)

        # docks
        self.surfaces_panel = SurfacesPanel()
        self.outputs_panel = OutputsPanel()
        tabs = QTabWidget()
        tabs.addTab(self.surfaces_panel, "Surfaces")
        tabs.addTab(self.outputs_panel, "Outputs")
        left = QDockWidget("Project", self)
        left.setWidget(tabs)
        left.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, left)

        self.media_panel = MediaPanel()
        media_dock = QDockWidget("Media", self)
        media_dock.setWidget(self.media_panel)
        media_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, media_dock)

        self.inspector = Inspector(self.engine)
        insp_dock = QDockWidget("Inspector", self)
        insp_dock.setWidget(self.inspector)
        insp_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, insp_dock)
        self.resizeDocks([media_dock, insp_dock], [250, 500], Qt.Orientation.Vertical)

        self.osc_panel = OscPanel()
        osc_dock = QDockWidget("OSC", self)
        osc_dock.setWidget(self.osc_panel)
        osc_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, osc_dock)
        self.tabifyDockWidget(left, osc_dock)
        left.raise_()
        self.osc_tree = OscTree(self)
        self.osc_server = OscServer(self._on_osc_message)
        self.osc_server.received.connect(lambda addr, args: self.osc_panel.add_log(f"{addr} {args}"))
        self.osc_server.error.connect(lambda text: self.osc_panel.add_log(text))
        self.osc_panel.settings_changed.connect(self._apply_osc_settings)
        self._osc_refresh = QTimer(self)
        self._osc_refresh.setSingleShot(True)
        self._osc_refresh.timeout.connect(self._refresh_after_osc)

        self._build_menus()
        self._connect()
        self.status_fps = QLabel("")
        self.statusBar().addPermanentWidget(self.status_fps)
        self.statusBar().showMessage("Ready. Drag corners in the stage view; drag input corners in the input view.")

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)
        self._fps_t0 = time.perf_counter()
        self._fps_n = 0
        self.refresh_all()
        self._last_state = self.snapshot()
        QTimer.singleShot(50, self.stage.fit_all)

    # ---- menus ----
    def _build_menus(self) -> None:
        mb = self.menuBar()
        fm = mb.addMenu("&File")
        self._act(fm, "&New project", QKeySequence.StandardKey.New, self.new_project)
        self._act(fm, "&Open...", QKeySequence.StandardKey.Open, self.open_dialog)
        self._act(fm, "&Save", QKeySequence.StandardKey.Save, self.save)
        self._act(fm, "Save &As...", QKeySequence.StandardKey.SaveAs, self.save_as)
        fm.addSeparator()
        self._act(fm, "&Import MadMapper project...", "Ctrl+I", self.import_mad_dialog)
        self._act(fm, "Import &media...", "Ctrl+M", lambda: self.add_media("image", ""))
        fm.addSeparator()
        self._act(fm, "&Quit", QKeySequence.StandardKey.Quit, self.close)

        em = mb.addMenu("&Edit")
        self._act(em, "&Undo", QKeySequence.StandardKey.Undo, self.undo)
        self._act(em, "&Redo", QKeySequence.StandardKey.Redo, self.redo)
        em.addSeparator()
        self._act(em, "&Duplicate surface", "Ctrl+D", lambda: self.surface_action("duplicate"))
        self._act(em, "Delete surface", "Delete", lambda: self.surface_action("delete"))
        self._act(em, "Bring forward", "Ctrl+]", lambda: self.surface_action("up"))
        self._act(em, "Send backward", "Ctrl+[", lambda: self.surface_action("down"))

        pm = mb.addMenu("&Project")
        self._act(pm, "Add &Quad", "Ctrl+Shift+Q", lambda: self.surface_action("add"))
        self._act(pm, "Add &Triangle", None, lambda: self.surface_action("add_triangle"))
        self._act(pm, "Add &Circle", None, lambda: self.surface_action("add_circle"))
        self._act(pm, "Add &Mask (black polygon)", "Alt+A", lambda: self.surface_action("add_mask"))
        self._act(pm, "Add &Output", "Ctrl+Shift+O", lambda: self.output_action("add"))
        self._act(pm, "Set &BPM...", None, self.set_bpm)

        om = mb.addMenu("&Output")
        self._act(om, "&Fullscreen selected output", "Ctrl+U", lambda: self.toggle_fullscreen(True))
        self._act(om, "E&xit fullscreen", "Ctrl+T", lambda: self.toggle_fullscreen(False))
        self._act(om, "Toggle &test pattern", "Ctrl+Shift+T", self.toggle_test_pattern)
        self._act(om, "Fit stage view", "F", self.stage.fit_all)

        hm = mb.addMenu("&Help")
        self._act(hm, "&About MapStudio", None, self.about)

    def _act(self, menu, text: str, shortcut, slot) -> QAction:
        a = QAction(text, self)
        if shortcut is not None:
            a.setShortcut(QKeySequence(shortcut) if isinstance(shortcut, str) else QKeySequence(shortcut))
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    def _connect(self) -> None:
        self.stage.selection_changed.connect(self.on_surface_selected)
        self.stage.geometry_edited.connect(self.mark_edit)
        self.stage.output_selected.connect(lambda o: self.outputs_panel.refresh(self.project, o))
        self.stage.request = self.surface_action
        self.input_view.uv_edited.connect(self.mark_edit)
        self.surfaces_panel.selected.connect(self.stage.select)
        self.surfaces_panel.changed.connect(self.mark_edit)
        self.surfaces_panel.action.connect(self.surface_action)
        self.outputs_panel.changed.connect(self.on_outputs_changed)
        self.outputs_panel.action.connect(self.output_action)
        self.outputs_panel.fullscreen_requested.connect(lambda o, fs: self.toggle_fullscreen(fs, o))
        self.outputs_panel.window_requested.connect(self.open_output_window)
        self.outputs_panel.selected.connect(self._on_output_selected)
        self.media_panel.selected.connect(self.on_visual_selected)
        self.media_panel.assign_requested.connect(self.assign_visual)
        self.media_panel.changed.connect(self.on_media_changed)
        self.media_panel.on_add = self.add_media
        self.inspector.surface_changed.connect(self.mark_edit)
        self.inspector.visual_changed.connect(lambda v: self.mark_edit())
        self.inspector.mask_edit_toggled.connect(self._set_mask_editing)

    # ---- OSC host hooks ----
    def selected_surface(self) -> QuadSurface | None:
        return self.stage.selected

    def select_surface(self, s: QuadSurface | None) -> None:
        self.stage.select(s)

    def selected_visual(self) -> Visual | None:
        return self.media_panel.current_visual()

    def select_visual(self, v: Visual) -> None:
        self.media_panel.refresh(self.project, v)
        self.on_visual_selected(v)

    def selected_output(self) -> Output | None:
        return self.stage.selected_output or self.outputs_panel.current

    def is_output_fullscreen(self, o: Output) -> bool:
        return o.id in self.output_windows

    def set_output_fullscreen(self, o: Output, on: bool) -> None:
        self.toggle_fullscreen(on, o)

    def after_osc_change(self) -> None:
        self._dirty = True
        self.stage.update()
        if not self._osc_refresh.isActive():
            self._osc_refresh.start(150)

    def _refresh_after_osc(self) -> None:
        self.on_surface_selected(self.stage.selected)
        self.outputs_panel.refresh(self.project, self.stage.selected_output)

    def _on_osc_message(self, msg: OscMessage, host: str, port: int) -> None:
        def reply(address: str, args: list) -> None:
            target_host = self.project.osc_feedback_host or host
            target_port = self.project.osc_feedback_port or port
            self.osc_server.send(address, args, target_host, target_port)
        if not self.osc_tree.dispatch(msg, reply):
            self.osc_panel.add_log(f"(unhandled) {msg.address}")

    def _apply_osc_settings(self) -> None:
        self.osc_panel.store(self.project)
        self._dirty = True
        self._sync_osc_server()

    def _sync_osc_server(self) -> None:
        p = self.project
        self.osc_server.feedback_host = p.osc_feedback_host
        self.osc_server.feedback_port = p.osc_feedback_port
        if p.osc_enabled:
            if self.osc_server.port != p.osc_port:
                ok = self.osc_server.start(p.osc_port)
                self.osc_panel.status.setText(f"OSC listening on UDP {p.osc_port}" if ok else "OSC: could not open port")
        else:
            self.osc_server.stop()
            self.osc_panel.status.setText("OSC off")

    # ---- frame ----
    def _tick(self) -> None:
        self._closing_windows.clear()
        if not self.engine.make_current():
            return
        try:
            self.engine.frame()
        finally:
            self.engine.done_current()
        self.stage.update()
        self.input_view.update()
        for w in self.output_windows.values():
            w.update()
        self._fps_n += 1
        now = time.perf_counter()
        if now - self._fps_t0 >= 1.0:
            fps = self._fps_n / (now - self._fps_t0)
            self._fps_t0, self._fps_n = now, 0
            errors = [f"{v.name}: {src.error}" for v in self.project.visuals
                      if (src := self.engine.sources.get(v.id)) is not None and src.error]
            errors += [f"{s.name} FX: {err}" for s in self.project.surfaces
                       if s.fx_active and s.fx_name and (err := self.engine.fx_error(s))]
            self.status_fps.setText(f"{fps:4.0f} fps   " + ("  |  ".join(errors)[:160] if errors else ""))

    # ---- refresh / selection ----
    def refresh_all(self) -> None:
        self.osc_panel.load(self.project)
        self._sync_osc_server()
        self.surfaces_panel.refresh(self.project, self.stage.selected)
        self.outputs_panel.refresh(self.project, self.stage.selected_output)
        self.media_panel.refresh(self.project)
        self.on_surface_selected(self.stage.selected)
        title = self.project.name + (" *" if self._dirty else "")
        self.setWindowTitle(f"MapStudio - {title}")

    def _set_mask_editing(self, on: bool) -> None:
        self.input_view.mask_mode = on
        self.input_view.active_mask = None
        self.input_view.update()

    def on_surface_selected(self, s: QuadSurface | None) -> None:
        if self.input_view.mask_mode and s is not self.input_view.surface:
            self.inspector.mask_editing = False
            self._set_mask_editing(False)
        self.input_view.set_surface(s)
        self.surfaces_panel.refresh(self.project, s)
        visual = self.project.visual(s.visual_id) if s is not None else None
        self.inspector.show_items(s, visual)

    def on_visual_selected(self, v: Visual | None) -> None:
        self.inspector.show_items(self.stage.selected if v is None else None, v)

    def _on_output_selected(self, o: Output | None) -> None:
        self.stage.selected_output = o
        self.stage.update()

    def on_outputs_changed(self) -> None:
        self.mark_edit()
        self.stage.update()

    def on_media_changed(self) -> None:
        self.mark_edit()
        self.media_panel.refresh(self.project)
        self.on_surface_selected(self.stage.selected)

    # ---- edits / undo ----
    def snapshot(self) -> dict:
        return self.project.to_dict()

    def mark_edit(self) -> None:
        """Record the state *after* an edit (the previous state was pushed by `begin_edit`)."""
        self._dirty = True
        self._push_undo_if_changed()
        self.setWindowTitle(f"MapStudio - {self.project.name} *")

    _last_state: dict | None = None

    def _push_undo_if_changed(self) -> None:
        cur = self.snapshot()
        if self._last_state is None:
            self._last_state = cur
            return
        if cur != self._last_state:
            self._undo.append(self._last_state)
            if len(self._undo) > UNDO_LIMIT:
                self._undo.pop(0)
            self._redo.clear()
            self._last_state = cur

    def _restore(self, state: dict) -> None:
        sel_id = self.stage.selected.id if self.stage.selected else None
        out_id = self.stage.selected_output.id if self.stage.selected_output else None
        self.project = Project.from_dict(copy.deepcopy(state))
        self.project.path = getattr(self, "_project_path", None)
        self.engine.project = self.project
        self._last_state = state
        self._dirty = True
        self.stage.selected = None
        self.stage.selected_output = self.project.output(out_id)
        for oid, w in list(self.output_windows.items()):   # re-point open windows to the restored outputs
            o = self.project.output(oid)
            if o is None:
                self.close_output_window(oid)
            else:
                w.output = o
        self.stage.select(self.project.surface(sel_id))
        self.refresh_all()
        self.stage.update()

    def undo(self) -> None:
        if not self._undo:
            return
        self._redo.append(self.snapshot())
        self._restore(self._undo.pop())

    def redo(self) -> None:
        if not self._redo:
            return
        self._undo.append(self.snapshot())
        self._restore(self._redo.pop())

    # ---- actions ----
    def surface_action(self, what: str) -> None:
        s = self.stage.selected
        p = self.project
        if what in ("add", "add_triangle", "add_circle", "add_mask"):
            o = self.stage.selected_output or (p.outputs[0] if p.outputs else None)
            centre = o.centre if o else (0.0, 0.0)
            size = min(o.size) * 0.6 if o else 2.0
            shape = {"add": Shape.QUAD, "add_triangle": Shape.TRIANGLE, "add_circle": Shape.CIRCLE, "add_mask": Shape.MASK}[what]
            if shape == Shape.MASK and s is not None:
                centre, size = s.centre(), min(s.bounds()[2] - s.bounds()[0], s.bounds()[3] - s.bounds()[1]) * 0.5
            q = p.add_quad(centre, size, shape=shape)
            if shape != Shape.MASK:
                if p.visuals and s is None:
                    q.visual_id = p.visuals[0].id
                elif s is not None:
                    q.visual_id = s.visual_id
            self.stage.select(q)
        elif s is None:
            return
        elif what == "duplicate":
            d = copy.deepcopy(s)
            from ..model.project import next_id
            d.id = next_id()
            d.name = p.unique_name(s.name, [x.name for x in p.surfaces])
            d.move(0.2, -0.2)
            p.surfaces.append(d)
            self.stage.select(d)
        elif what == "delete":
            p.remove_surface(s.id)
            self.stage.select(None)
        elif what == "up":
            i = p.surfaces.index(s)
            if i < len(p.surfaces) - 1:
                p.surfaces[i], p.surfaces[i + 1] = p.surfaces[i + 1], p.surfaces[i]
        elif what == "down":
            i = p.surfaces.index(s)
            if i > 0:
                p.surfaces[i], p.surfaces[i - 1] = p.surfaces[i - 1], p.surfaces[i]
        elif what == "reset":
            l, b, r, t = s.bounds()
            if s.shape == Shape.TRIANGLE:
                s.corners = [(l, b), (r, b), ((l + r) / 2, t)]
            elif s.shape == Shape.MASK:
                s.corners = [(l, b), (r, b), (r, t), (l, t)]
            else:
                s.corners = [(l, b), (r, b), (r, t), (l, t)]
            s.warp_points = []
            s.warp_cols = s.warp_rows = 0
            self.stage.active_handle = None
        elif what == "warp_on":
            s.warp_cols = s.warp_rows = 4
            s.warp_points = bilinear_grid(s.corners, 4, 4)
            self.stage.active_handle = None
        elif what == "warp_reset":
            s.warp_points = bilinear_grid(s.corners, s.warp_cols, s.warp_rows)
        elif what == "warp_off":
            s.warp_points = []
            s.warp_cols = s.warp_rows = 0
            self.stage.active_handle = None
        elif what == "toggle_perspective":
            s.perspective = not s.perspective
        self.mark_edit()
        self.refresh_all()
        self.stage.update()

    def output_action(self, what: str) -> None:
        p = self.project
        if what == "add":
            o = p.add_output()
            self.stage.selected_output = o
        elif what == "delete":
            o = self.outputs_panel.current
            if o is None:
                return
            self.close_output_window(o.id)
            p.remove_output(o.id)
            self.stage.selected_output = None
        self.mark_edit()
        self.refresh_all()
        self.stage.fit_all()

    def set_bpm(self) -> None:
        v, ok = QInputDialog.getDouble(self, "Global BPM", "Beats per minute", self.project.bpm, 20.0, 400.0, 1)
        if ok:
            self.project.bpm = v
            self.mark_edit()

    def toggle_test_pattern(self) -> None:
        o = self.stage.selected_output or self.outputs_panel.current or (self.project.outputs[0] if self.project.outputs else None)
        if o is not None:
            o.test_pattern = not o.test_pattern
            self.outputs_panel.refresh(self.project, o)
            self.mark_edit()

    # ---- media ----
    def add_media(self, kind: str, arg: str) -> None:
        p = self.project
        v: Visual | None = None
        if kind == "image":
            files, _ = QFileDialog.getOpenFileNames(self, "Add images", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp)")
            for f in files:
                v = p.add_visual(VisualKind.IMAGE, Path(f).name, f)
        elif kind == "movie":
            files, _ = QFileDialog.getOpenFileNames(self, "Add movies", "", "Movies (*.mp4 *.mov *.avi *.mkv *.webm *.m4v *.wmv)")
            for f in files:
                v = p.add_visual(VisualKind.MOVIE, Path(f).name, f)
        elif kind == "material":
            folder = arg
            if not folder:
                folder = QFileDialog.getExistingDirectory(self, "Material folder (containing one .fs)")
            if folder:
                v = p.add_visual(VisualKind.MATERIAL, Path(folder).name, folder)
        elif kind == "solid":
            v = p.add_visual(VisualKind.SOLID, "Solid Color", "", color=[1.0, 1.0, 1.0, 1.0])
        elif kind == "test_card":
            v = p.add_visual(VisualKind.TEST_CARD, "Test Card", "")
        elif kind == "loopback":
            names = [f"{o.name} ({o.id})" for o in p.outputs]
            if not names:
                return
            choice, ok = QInputDialog.getItem(self, "Output loopback", "Output to capture", names, 0, False)
            if not ok:
                return
            o = p.outputs[names.index(choice)]
            v = p.add_visual(VisualKind.OUTPUT_LOOPBACK, f"Loopback {o.name}", str(o.id))
        if v is None:
            return
        self.mark_edit()
        self.media_panel.refresh(self.project, v)
        self.on_visual_selected(v)

    def assign_visual(self, v: Visual) -> None:
        s = self.stage.selected
        if s is None:
            self.statusBar().showMessage("Select a surface first, then assign media.", 4000)
            return
        s.visual_id = v.id
        self.mark_edit()
        self.on_surface_selected(s)
        self.stage.update()

    # ---- outputs / fullscreen ----
    def _output_window_closed(self, w: OutputWindow) -> None:
        if self.output_windows.get(w.output.id) is w:
            del self.output_windows[w.output.id]
        self._closing_windows.append(w)
        w.deleteLater()

    def open_output_window(self, o: Output) -> None:
        self.close_output_window(o.id)
        w = OutputWindow(self.engine, o, self._output_window_closed)
        self.output_windows[o.id] = w
        w.go_windowed()

    def toggle_fullscreen(self, fullscreen: bool, o: Output | None = None) -> None:
        o = o or self.stage.selected_output or self.outputs_panel.current or (self.project.outputs[0] if self.project.outputs else None)
        if o is None:
            return
        if not fullscreen:
            self.close_output_window(o.id)
            return
        screen = next((s for s in QGuiApplication.screens() if s.name() == o.screen_name), None)
        if screen is None:
            screens = QGuiApplication.screens()
            others = [s for s in screens if s is not self.screen()]
            screen = others[0] if others else screens[0]
            o.screen_name = screen.name()
            self.outputs_panel.refresh(self.project, o)
        self.close_output_window(o.id)
        w = OutputWindow(self.engine, o, self._output_window_closed)
        self.output_windows[o.id] = w
        w.go_fullscreen(screen)

    def close_output_window(self, oid: int) -> None:
        w = self.output_windows.get(oid)
        if w is not None:
            w.close()   # closeEvent hands the window to _output_window_closed

    # ---- files ----
    def new_project(self) -> None:
        if not self._confirm_discard():
            return
        self._load_project(new_default_project(), None)

    def open_dialog(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "", "MapStudio project (*.mapstudio);;MadMapper project (*.mad)")
        if path:
            self.open_any(Path(path))

    def open_any(self, path: Path) -> None:
        try:
            if path.suffix.lower() == ".mapstudio":
                self._load_project(load_project(path), str(path))
            elif path.suffix.lower() in (".mad", ".madproject") or path.is_dir():
                self.import_mad(path)
            else:
                raise ProjectError(f"unknown project type: {path.name}")
        except (ProjectError, MadFileError, OSError, ValueError, TypeError, KeyError, IndexError) as exc:
            QMessageBox.critical(self, "Cannot open", f"{path.name}: {exc}")

    def import_mad_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import MadMapper project", "", "MadMapper project (*.mad)")
        if path:
            try:
                self.import_mad(Path(path))
            except (MadFileError, OSError, ValueError, TypeError, KeyError, IndexError) as exc:
                QMessageBox.critical(self, "Import failed", str(exc))

    def import_mad(self, path: Path) -> None:
        project, report = import_mad_project(path)
        self._load_project(project, None)
        self._dirty = True
        self.statusBar().showMessage(f"Imported {path.name}: {len(report.imported)} items, {len(report.skipped)} skipped", 8000)
        print(report.summary(), file=sys.stderr)
        if (report.skipped or report.warnings) and not self.quiet:
            QMessageBox.information(self, "Import report", report.summary()[:4000])

    def _load_project(self, project: Project, path: str | None) -> None:
        for oid in list(self.output_windows):
            self.close_output_window(oid)
        self.project = project
        self._project_path = path
        project.path = path
        self.engine.set_project(project)
        self._undo.clear()
        self._redo.clear()
        self._last_state = self.snapshot()
        self._dirty = False
        self.stage.selected = None
        self.stage.selected_output = None
        self.refresh_all()
        self.stage.fit_all()

    def save(self) -> None:
        path = getattr(self, "_project_path", None) or self.project.path
        if not path:
            self.save_as()
            return
        try:
            save_project(self.project, path)
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self._project_path = self.project.path
        self._dirty = False
        self.refresh_all()
        self.statusBar().showMessage(f"Saved {path}", 4000)

    def save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save project", self.project.name + ".mapstudio", "MapStudio project (*.mapstudio)")
        if path:
            self.project.name = Path(path).stem
            self._project_path = path
            self.save()

    def _confirm_discard(self) -> bool:
        if not self._dirty or self.quiet:
            return True
        r = QMessageBox.question(self, "Unsaved changes", "Discard unsaved changes?",
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        return r == QMessageBox.StandardButton.Yes

    def about(self) -> None:
        QMessageBox.about(self, "MapStudio", "MapStudio 0.1\nAn educational projection-mapping application modelled on MadMapper.\n"
                          "Reads MadMapper .mad projects and ISF materials; renders corner-pinned surfaces with soft edges to outputs.")

    def closeEvent(self, e: QCloseEvent) -> None:
        if not self._confirm_discard():
            e.ignore()
            return
        self.timer.stop()
        self.osc_server.stop()
        for oid in list(self.output_windows):
            self.close_output_window(oid)
        super().closeEvent(e)

    # ---- diagnostics ----
    def save_screenshots(self, folder: Path) -> None:
        """Save PNGs of the stage view, the input view and every output (rendered at full size)."""
        self.stage.grab().save(str(folder / "stage.png"))
        self.input_view.grab().save(str(folder / "input.png"))
        if self.engine.make_current():
            try:
                for o in self.project.outputs:
                    fbo = make_fbo(*o.pixel_size)
                    fbo.bind()
                    self.engine.draw_stage(ViewRect.for_output(o), o.pixel_size, outputs=[o], clip_to_outputs=True)
                    fbo.release()
                    fbo.toImage().save(str(folder / f"output-{o.id}-{_safe(o.name)}.png"))
            finally:
                self.engine.done_current()
        report = {
            "project": self.project.name,
            "surfaces": [s.name for s in self.project.surfaces],
            "visuals": {v.name: (self.engine.sources[v.id].error if v.id in self.engine.sources else "no source") for v in self.project.visuals},
            "frames": self.engine.frame_count,
        }
        (folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
