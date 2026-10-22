"""OpenGL views: the stage (output preview), the input view and fullscreen output windows."""
from __future__ import annotations

import math
from typing import Callable

from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QSize
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QBrush, QMouseEvent, QWheelEvent, QKeyEvent, QFont, QImage, QScreen, QCursor,
)
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QMenu, QWidget

from ..model import Project, QuadSurface, Output, Shape
from ..render import RenderEngine, ViewRect
from ..render.geometry import point_in_polygon, distance, bilinear_grid, quad_from_grid
from ..render.gl import forget_context_funcs

HANDLE_RADIUS = 6.0
PICK_RADIUS = 10.0


class _Overlay(QWidget):
    """A raster-painted child widget drawn over a GL view.

    Painting handles and labels with QPainter directly inside paintGL forces a GL/QPainter sync
    that waits for the GPU every frame (measured at ~14 ms with three materials rendering); a
    sibling raster widget composes for free and lets mouse events through to the GL view.
    """

    def __init__(self, parent: QWidget, painter: Callable[[QPainter], None]):
        super().__init__(parent)
        self._painter = painter
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._painter(p)
        p.end()


class StageView(QOpenGLWidget):
    """The output preview: all outputs laid out on the stage, surfaces editable by their corners."""
    selection_changed = pyqtSignal(object)     # QuadSurface | None
    geometry_edited = pyqtSignal()             # a surface or output moved (for undo)
    output_selected = pyqtSignal(object)       # Output | None

    def __init__(self, engine: RenderEngine, parent: QWidget | None = None):
        super().__init__(parent)
        self.engine = engine
        self.centre = (0.0, 0.0)
        self.zoom = 100.0                       # pixels per stage unit
        self.selected: QuadSurface | None = None
        self.selected_output: Output | None = None
        self.active_handle: int | None = None   # corner / warp point index being dragged
        self.hover_handle: int | None = None
        self._drag_mode: str | None = None      # "handle" | "surface" | "pan" | "output"
        self._last_pos = QPointF()
        self._drag_changed = False
        self.show_labels = True
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(320, 180)
        self.overlay = _Overlay(self, self._draw_overlay)

    @property
    def project(self) -> Project:
        return self.engine.project

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.overlay.setGeometry(self.rect())

    def update(self) -> None:  # type: ignore[override]
        super().update()
        self.overlay.update()

    # ---- view transform ----
    def view_rect(self) -> ViewRect:
        w, h = max(self.width(), 1), max(self.height(), 1)
        hw, hh = w / (2 * self.zoom), h / (2 * self.zoom)
        return ViewRect(self.centre[0] - hw, self.centre[1] - hh, self.centre[0] + hw, self.centre[1] + hh)

    def to_screen(self, p: tuple[float, float]) -> QPointF:
        vr = self.view_rect()
        x = (p[0] - vr.left) / vr.width * self.width()
        y = (1 - (p[1] - vr.bottom) / vr.height) * self.height()
        return QPointF(x, y)

    def to_stage(self, q: QPointF) -> tuple[float, float]:
        vr = self.view_rect()
        x = vr.left + q.x() / max(self.width(), 1) * vr.width()
        y = vr.bottom + (1 - q.y() / max(self.height(), 1)) * vr.height()
        return (x, y)

    def fit_all(self) -> None:
        l, b, r, t = self.project.stage_bounds()
        margin = 0.5
        l, b, r, t = l - margin, b - margin, r + margin, t + margin
        self.centre = ((l + r) / 2, (b + t) / 2)
        self.zoom = min(self.width() / max(r - l, 1e-6), self.height() / max(t - b, 1e-6))
        self.update()

    # ---- GL ----
    def initializeGL(self) -> None:
        self.engine.ensure_programs()

    def paintGL(self) -> None:
        self.engine.draw_stage(self.view_rect(), (int(self.width() * self.devicePixelRatioF()),
                                                  int(self.height() * self.devicePixelRatioF())),
                               clear=(0.11, 0.11, 0.12, 1.0), clip_to_outputs=True, placeholders=True)

    def _draw_overlay(self, p: QPainter) -> None:
        font = QFont()
        font.setPointSize(9)
        p.setFont(font)
        for o in self.project.outputs:
            l, b, r, t = o.rect()
            tl, br = self.to_screen((l, t)), self.to_screen((r, b))
            rect = QRectF(tl, br)
            pen = QPen(QColor(255, 200, 60) if o is self.selected_output else QColor(120, 160, 230), 1.5 if o is self.selected_output else 1.0)
            if o.is_buffer:
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect)
            if self.show_labels:
                label = f"{o.name}  {o.pixel_size[0]}x{o.pixel_size[1]}" + ("  (buffer)" if o.is_buffer else "")
                p.setPen(QColor(230, 230, 230))
                p.drawText(QPointF(tl.x() + 6, tl.y() + 16), label)
        for s in self.project.surfaces:
            if not s.visible:
                continue
            pts = [self.to_screen(c) for c in s.corners]
            sel = s is self.selected
            col = QColor(255, 200, 60) if sel else QColor(255, 255, 255, 110)
            if s.shape == Shape.MASK:
                col = QColor(255, 90, 200) if sel else QColor(255, 90, 200, 140)
            p.setPen(QPen(col, 1.5 if sel else 1.0))
            n = len(pts)
            for i in range(n):
                p.drawLine(pts[i], pts[(i + 1) % n])
            if sel and s.warp_points:
                self._draw_warp_grid(p, s)
            if self.show_labels:
                c = self.to_screen(s.centre())
                p.setPen(QColor(255, 255, 255, 200))
                p.drawText(QPointF(c.x() - 20, c.y()), s.name)
        if self.selected is not None and self.selected.visible:
            handles = self.handle_points(self.selected)
            for i, hp in enumerate(handles):
                q = self.to_screen(hp)
                active = i == self.active_handle or i == self.hover_handle
                p.setPen(QPen(QColor(20, 20, 20), 1))
                p.setBrush(QBrush(QColor(255, 120, 40) if active else QColor(255, 200, 60)))
                r = HANDLE_RADIUS + (2 if active else 0)
                p.drawEllipse(q, r, r)

    def _draw_warp_grid(self, p: QPainter, s: QuadSurface) -> None:
        stride = s.warp_cols + 1
        p.setPen(QPen(QColor(255, 200, 60, 120), 1))
        for j in range(s.warp_rows + 1):
            for i in range(s.warp_cols + 1):
                a = self.to_screen(s.warp_points[j * stride + i])
                if i < s.warp_cols:
                    p.drawLine(a, self.to_screen(s.warp_points[j * stride + i + 1]))
                if j < s.warp_rows:
                    p.drawLine(a, self.to_screen(s.warp_points[(j + 1) * stride + i]))

    # ---- editing helpers ----
    def handle_points(self, s: QuadSurface) -> list[tuple[float, float]]:
        return list(s.warp_points) if s.warp_points else list(s.corners)

    def set_handle(self, s: QuadSurface, index: int, pos: tuple[float, float]) -> None:
        if s.warp_points:
            s.warp_points[index] = pos
            s.corners = quad_from_grid(s.warp_points, s.warp_cols, s.warp_rows)
        else:
            s.corners[index] = pos

    def surface_at(self, stage_pt: tuple[float, float]) -> QuadSurface | None:
        for s in reversed(self.project.surfaces):    # topmost first
            if s.visible and not s.locked and point_in_polygon(stage_pt, s.corners):
                return s
        return None

    def output_label_at(self, q: QPointF) -> Output | None:
        for o in self.project.outputs:
            l, b, r, t = o.rect()
            tl = self.to_screen((l, t))
            if QRectF(tl.x(), tl.y(), 160, 20).contains(q):
                return o
        return None

    def handle_at(self, q: QPointF) -> int | None:
        if self.selected is None:
            return None
        best, best_d = None, PICK_RADIUS
        for i, hp in enumerate(self.handle_points(self.selected)):
            d = distance((q.x(), q.y()), (self.to_screen(hp).x(), self.to_screen(hp).y()))
            if d < best_d:
                best, best_d = i, d
        return best

    def select(self, s: QuadSurface | None) -> None:
        if s is not self.selected:
            self.selected = s
            self.active_handle = None
            self.selection_changed.emit(s)
        self.update()

    # ---- mouse ----
    def mousePressEvent(self, e: QMouseEvent) -> None:
        self.setFocus()
        q = e.position()
        self._last_pos = q
        self._drag_changed = False
        if e.button() == Qt.MouseButton.MiddleButton or (e.button() == Qt.MouseButton.LeftButton and e.modifiers() & Qt.KeyboardModifier.AltModifier):
            self._drag_mode = "pan"
            return
        if e.button() == Qt.MouseButton.LeftButton:
            h = self.handle_at(q)
            if h is not None:
                self.active_handle = h
                self._drag_mode = "handle"
                self.update()
                return
            o = self.output_label_at(q)
            if o is not None:
                self.selected_output = o
                self.output_selected.emit(o)
                self._drag_mode = "output"
                self.update()
                return
            s = self.surface_at(self.to_stage(q))
            self.select(s)
            self._drag_mode = "surface" if s is not None else None
        elif e.button() == Qt.MouseButton.RightButton:
            s = self.surface_at(self.to_stage(q))
            if s is not None:
                self.select(s)
            self._context_menu(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        q = e.position()
        d = q - self._last_pos
        if self._drag_mode == "pan":
            self.centre = (self.centre[0] - d.x() / self.zoom, self.centre[1] + d.y() / self.zoom)
            self._last_pos = q
            self.update()
            return
        if self._drag_mode == "handle" and self.selected is not None and self.active_handle is not None:
            pos = self.to_stage(q)
            if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:   # snap to 0.1 units
                pos = (round(pos[0] * 10) / 10, round(pos[1] * 10) / 10)
            self.set_handle(self.selected, self.active_handle, pos)
            self._drag_changed = True
            self.update()
            return
        if self._drag_mode == "surface" and self.selected is not None:
            self.selected.move(d.x() / self.zoom, -d.y() / self.zoom)
            self._last_pos = q
            self._drag_changed = True
            self.update()
            return
        if self._drag_mode == "output" and self.selected_output is not None:
            o = self.selected_output
            o.centre = (o.centre[0] + d.x() / self.zoom, o.centre[1] - d.y() / self.zoom)
            self._last_pos = q
            self._drag_changed = True
            self.update()
            return
        hh = self.handle_at(q)
        if hh != self.hover_handle:
            self.hover_handle = hh
            self.update()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if self._drag_changed:
            self.geometry_edited.emit()
        self._drag_mode = None
        self._drag_changed = False
        self.update()

    def wheelEvent(self, e: QWheelEvent) -> None:
        factor = 1.0015 ** e.angleDelta().y()
        anchor = self.to_stage(e.position())
        self.zoom = max(5.0, min(5000.0, self.zoom * factor))
        after = self.to_stage(e.position())
        self.centre = (self.centre[0] + anchor[0] - after[0], self.centre[1] + anchor[1] - after[1])
        self.update()

    def keyPressEvent(self, e: QKeyEvent) -> None:
        s = self.selected
        step = (10.0 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0) / self.zoom
        moves = {Qt.Key.Key_Left: (-step, 0), Qt.Key.Key_Right: (step, 0), Qt.Key.Key_Up: (0, step), Qt.Key.Key_Down: (0, -step)}
        if s is not None and self.active_handle is not None and self.active_handle >= len(self.handle_points(s)):
            self.active_handle = None
        if s is not None and e.key() in moves:
            dx, dy = moves[e.key()]
            if self.active_handle is not None:
                hp = self.handle_points(s)[self.active_handle]
                self.set_handle(s, self.active_handle, (hp[0] + dx, hp[1] + dy))
            else:
                s.move(dx, dy)
            self.geometry_edited.emit()
            self.update()
            return
        if s is not None and e.key() == Qt.Key.Key_Tab:
            n = len(self.handle_points(s))
            self.active_handle = 0 if self.active_handle is None else (self.active_handle + 1) % n
            self.update()
            return
        if e.key() == Qt.Key.Key_Escape:
            self.active_handle = None
            self.select(None)
            return
        if e.key() == Qt.Key.Key_F:
            self.fit_all()
            return
        super().keyPressEvent(e)

    def _context_menu(self, e: QMouseEvent) -> None:
        menu = QMenu(self)
        s = self.selected
        if s is not None:
            menu.addAction("Duplicate", lambda: self.request("duplicate"))
            menu.addAction("Delete", lambda: self.request("delete"))
            menu.addSeparator()
            menu.addAction("Reset to rectangle", lambda: self.request("reset"))
            if s.warp_points:
                menu.addAction("Disable mesh warp", lambda: self.request("warp_off"))
                menu.addAction("Reset mesh warp", lambda: self.request("warp_reset"))
            else:
                menu.addAction("Enable mesh warp (4 x 4)", lambda: self.request("warp_on"))
            menu.addAction("Perspective" if not s.perspective else "Affine (no perspective)", lambda: self.request("toggle_perspective"))
            menu.addSeparator()
        menu.addAction("Fit all (F)", self.fit_all)
        menu.exec(e.globalPosition().toPoint())

    # callbacks set by the main window
    request: Callable[[str], None] = lambda self, what: None  # type: ignore[assignment]

    def sizeHint(self) -> QSize:
        return QSize(960, 540)


class InputView(QOpenGLWidget):
    """Shows the selected surface's media and lets the user drag its input (uv) corners."""
    uv_edited = pyqtSignal()

    def __init__(self, engine: RenderEngine, parent: QWidget | None = None):
        super().__init__(parent)
        self.engine = engine
        self.surface: QuadSurface | None = None
        self.active: int | None = None
        self.hover: int | None = None
        self._last = QPointF()
        self._drag_all = False
        self._changed = False
        self.setMouseTracking(True)
        self.setMinimumSize(240, 135)
        self._preview = QuadSurface(-1, "preview", [(0, 0), (1, 0), (1, 1), (0, 1)])
        self.overlay = _Overlay(self, self._draw_overlay)
        self.mask_mode = False          # when True the handles edit the layer mask polygon
        self.active_mask: int | None = None

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.overlay.setGeometry(self.rect())

    def update(self) -> None:  # type: ignore[override]
        super().update()
        self.overlay.update()

    def set_surface(self, s: QuadSurface | None) -> None:
        self.surface = s
        self.active = None
        self.update()

    def image_rect(self) -> QRectF:
        """Where the media is drawn (letterboxed, y up)."""
        w, h = max(self.width(), 1), max(self.height(), 1)
        tex = None
        if self.surface is not None:
            tex = self.engine.texture_for_visual(self.engine.project.visual(self.surface.visual_id))
        aspect = (tex.width / tex.height) if tex and tex.height else 16 / 9
        margin = 24
        aw, ah = w - 2 * margin, h - 2 * margin
        if aw / ah > aspect:
            rh = ah
            rw = ah * aspect
        else:
            rw = aw
            rh = aw / aspect
        return QRectF((w - rw) / 2, (h - rh) / 2, rw, rh)

    def uv_to_screen(self, uv: tuple[float, float]) -> QPointF:
        r = self.image_rect()
        return QPointF(r.left() + uv[0] * r.width(), r.bottom() - uv[1] * r.height())

    def screen_to_uv(self, q: QPointF) -> tuple[float, float]:
        r = self.image_rect()
        return ((q.x() - r.left()) / max(r.width(), 1e-6), (r.bottom() - q.y()) / max(r.height(), 1e-6))

    def local_to_screen(self, lc: tuple[float, float]) -> QPointF:
        """Surface-local (0..1 across the input quad) -> screen, bilinear in the uv corners."""
        s = self.surface
        assert s is not None
        uv = s.uv_corners
        if len(uv) == 4:
            u, v = lc
            (u0, v0), (u1, v1), (u2, v2), (u3, v3) = uv
            x = (1 - u) * (1 - v) * u0 + u * (1 - v) * u1 + u * v * u2 + (1 - u) * v * u3
            y = (1 - u) * (1 - v) * v0 + u * (1 - v) * v1 + u * v * v2 + (1 - u) * v * v3
            return self.uv_to_screen((x, y))
        return self.uv_to_screen(lc)

    def screen_to_local(self, q: QPointF) -> tuple[float, float]:
        """Inverse of local_to_screen for the (near-rectangular) uv quads: solved by iteration."""
        s = self.surface
        assert s is not None
        target = self.screen_to_uv(q)
        uv = s.uv_corners
        if len(uv) != 4:
            return target
        (u0, v0), (u1, v1), (u2, v2), (u3, v3) = uv
        lx, ly = 0.5, 0.5
        for _ in range(12):   # Newton iterations on the bilinear map
            x = (1 - lx) * (1 - ly) * u0 + lx * (1 - ly) * u1 + lx * ly * u2 + (1 - lx) * ly * u3
            y = (1 - lx) * (1 - ly) * v0 + lx * (1 - ly) * v1 + lx * ly * v2 + (1 - lx) * ly * v3
            dxdu = -(1 - ly) * u0 + (1 - ly) * u1 + ly * u2 - ly * u3
            dxdv = -(1 - lx) * u0 - lx * u1 + lx * u2 + (1 - lx) * u3
            dydu = -(1 - ly) * v0 + (1 - ly) * v1 + ly * v2 - ly * v3
            dydv = -(1 - lx) * v0 - lx * v1 + lx * v2 + (1 - lx) * v3
            det = dxdu * dydv - dxdv * dydu
            if abs(det) < 1e-12:
                break
            ex, ey = target[0] - x, target[1] - y
            lx += (ex * dydv - ey * dxdv) / det
            ly += (ey * dxdu - ex * dydu) / det
        return (lx, ly)

    def _mask_handle_at(self, q: QPointF) -> int | None:
        if self.surface is None or not self.surface.mask_points:
            return None
        best, bd = None, PICK_RADIUS
        for i, m in enumerate(self.surface.mask_points):
            sp = self.local_to_screen(m)
            d = distance((q.x(), q.y()), (sp.x(), sp.y()))
            if d < bd:
                best, bd = i, d
        return best

    def initializeGL(self) -> None:
        self.engine.ensure_programs()

    def paintGL(self) -> None:
        r = self.image_rect()
        w, h = max(self.width(), 1), max(self.height(), 1)
        # map the widget to a stage-like rect where the image occupies 0..1
        vr = ViewRect(-r.left() / r.width(), -(h - r.bottom()) / r.height(),
                      (w - r.left()) / r.width(), r.bottom() / r.height())
        dpr = self.devicePixelRatioF()
        if self.surface is not None:
            self._preview.visual_id = self.surface.visual_id
            self._preview.flip_h, self._preview.flip_v = self.surface.flip_h, self.surface.flip_v
            self.engine.draw_stage(vr, (int(w * dpr), int(h * dpr)), only_surface=self._preview,
                                   clear=(0.09, 0.09, 0.1, 1.0), placeholders=True)
        else:
            self.engine.clear_target((int(w * dpr), int(h * dpr)), (0.09, 0.09, 0.1, 1.0))

    def _draw_overlay(self, p: QPainter) -> None:
        r = self.image_rect()
        p.setPen(QPen(QColor(90, 90, 95), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r)
        if self.surface is not None:
            pts = [self.uv_to_screen(uv) for uv in self.surface.uv_corners]
            p.setPen(QPen(QColor(90, 200, 255), 1.5))
            n = len(pts)
            for i in range(n):
                p.drawLine(pts[i], pts[(i + 1) % n])
            for i, q in enumerate(pts):
                act = not self.mask_mode and (i == self.active or i == self.hover)
                p.setPen(QPen(QColor(20, 20, 20), 1))
                p.setBrush(QBrush(QColor(255, 120, 40) if act else QColor(90, 200, 255)))
                rr = HANDLE_RADIUS + (2 if act else 0)
                p.drawEllipse(q, rr, rr)
            if self.surface.mask_points:
                mpts = [self.local_to_screen(m) for m in self.surface.mask_points]
                p.setPen(QPen(QColor(255, 90, 200), 1.5, Qt.PenStyle.DashLine if not self.mask_mode else Qt.PenStyle.SolidLine))
                for i in range(len(mpts)):
                    p.drawLine(mpts[i], mpts[(i + 1) % len(mpts)])
                if self.mask_mode:
                    for i, q in enumerate(mpts):
                        act = i == self.active_mask or i == self.hover
                        p.setPen(QPen(QColor(20, 20, 20), 1))
                        p.setBrush(QBrush(QColor(255, 120, 40) if act else QColor(255, 90, 200)))
                        rr = HANDLE_RADIUS + (2 if act else 0)
                        p.drawEllipse(q, rr, rr)
            p.setPen(QColor(220, 220, 220))
            label = f"Input: {self.surface.name}"
            if self.mask_mode:
                label += "   [mask editing: drag points, Alt+click adds, right-click removes]"
            p.drawText(QPointF(8, 16), label)
        else:
            p.setPen(QColor(160, 160, 160))
            p.drawText(QPointF(8, 16), "Input view: select a surface")

    def _handle_at(self, q: QPointF) -> int | None:
        if self.surface is None:
            return None
        best, bd = None, PICK_RADIUS
        for i, uv in enumerate(self.surface.uv_corners):
            d = distance((q.x(), q.y()), (self.uv_to_screen(uv).x(), self.uv_to_screen(uv).y()))
            if d < bd:
                best, bd = i, d
        return best

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if self.surface is None:
            return
        self._last = e.position()
        self._changed = False
        if self.mask_mode:
            s = self.surface
            if e.button() == Qt.MouseButton.RightButton:
                h = self._mask_handle_at(e.position())
                if h is not None and len(s.mask_points) > 3:
                    del s.mask_points[h]
                    self.active_mask = None
                    self.uv_edited.emit()
                self.update()
                return
            if e.button() != Qt.MouseButton.LeftButton:
                return
            if e.modifiers() & Qt.KeyboardModifier.AltModifier and s.mask_points:
                lc = self.screen_to_local(e.position())
                # insert after the closest edge
                best, bi = 1e9, 0
                n = len(s.mask_points)
                for i in range(n):
                    a, b = s.mask_points[i], s.mask_points[(i + 1) % n]
                    d = _point_segment_distance(lc, a, b)
                    if d < best:
                        best, bi = d, i
                s.mask_points.insert(bi + 1, lc)
                self.active_mask = bi + 1
                self.uv_edited.emit()
                self.update()
                return
            self.active_mask = self._mask_handle_at(e.position())
            self.update()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        h = self._handle_at(e.position())
        self.active = h
        self._drag_all = h is None and point_in_polygon(self.screen_to_uv(e.position()), self.surface.uv_corners)
        self.update()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self.surface is None:
            return
        q = e.position()
        if self.mask_mode:
            if e.buttons() & Qt.MouseButton.LeftButton and self.active_mask is not None:
                self.surface.mask_points[self.active_mask] = self.screen_to_local(q)
                self._changed = True
                self.update()
                return
            hh = self._mask_handle_at(q)
            if hh != self.hover:
                self.hover = hh
                self.update()
            return
        if e.buttons() & Qt.MouseButton.LeftButton:
            if self.active is not None:
                uv = self.screen_to_uv(q)
                if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    uv = (round(uv[0] * 20) / 20, round(uv[1] * 20) / 20)
                self.surface.uv_corners[self.active] = uv
                self._changed = True
            elif self._drag_all:
                r = self.image_rect()
                d = q - self._last
                du, dv = d.x() / r.width(), -d.y() / r.height()
                self.surface.uv_corners = [(u + du, v + dv) for u, v in self.surface.uv_corners]
                self._last = q
                self._changed = True
            self.update()
            return
        hh = self._handle_at(q)
        if hh != self.hover:
            self.hover = hh
            self.update()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if self._changed:
            self.uv_edited.emit()
        self._drag_all = False
        self._changed = False

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        if self.surface is not None and not self.mask_mode:
            n = len(self.surface.uv_corners)
            self.surface.uv_corners = [(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)] if n == 3 else [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
            self.uv_edited.emit()
            self.update()


def _point_segment_distance(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / l2))
    return distance(p, (ax + t * dx, ay + t * dy))

    def sizeHint(self) -> QSize:
        return QSize(480, 270)


class OutputWindow(QOpenGLWidget):
    """A top-level window showing exactly one output (fullscreen on its screen or windowed)."""

    def __init__(self, engine: RenderEngine, output: Output, on_close: Callable[["OutputWindow"], None]):
        super().__init__(None)
        self.engine = engine
        self.output = output
        self._on_close = on_close
        self._closed = False
        self.setWindowTitle(f"MapStudio output: {output.name}")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setCursor(QCursor(Qt.CursorShape.BlankCursor))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def go_fullscreen(self, screen: QScreen) -> None:
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.showFullScreen()

    def go_windowed(self) -> None:
        self.setWindowFlags(Qt.WindowType.Window)
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        w, h = self.output.pixel_size
        self.resize(w // 2, h // 2)
        self.showNormal()

    def initializeGL(self) -> None:
        self.engine.ensure_programs()

    def paintGL(self) -> None:
        dpr = self.devicePixelRatioF()
        self.engine.draw_stage(ViewRect.for_output(self.output), (int(self.width() * dpr), int(self.height() * dpr)),
                               outputs=[self.output], clip_to_outputs=True)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape or (e.key() == Qt.Key.Key_T and e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.close()
            return
        super().keyPressEvent(e)

    def closeEvent(self, e) -> None:
        super().closeEvent(e)
        if not self._closed:
            self._closed = True
            # The owner keeps a reference until the next frame so the C++ object is not deleted
            # while Qt is still inside close().
            self._on_close(self)
