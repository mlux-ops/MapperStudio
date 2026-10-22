"""Side panels: surfaces list, outputs, media bin, the property inspector and the OSC panel."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import Qt, pyqtSignal, QSignalBlocker
from PyQt6.QtGui import QColor, QGuiApplication
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QLabel, QLineEdit,
    QCheckBox, QDoubleSpinBox, QSpinBox, QComboBox, QSlider, QGroupBox, QFormLayout, QScrollArea,
    QColorDialog, QFileDialog, QMenu, QToolButton, QSizePolicy, QFrame,
)

from ..model import Project, QuadSurface, Output, Visual, VisualKind, BlendMode, Shape
from ..isf.inputs import InputType, IsfInput
from ..render import RenderEngine
from ..render.media import MaterialSourceGL
from ..render.fx import library_fx_names
from ..model.mad_import import MADMAPPER_LIBRARY_CANDIDATES
from ..osc.tree import OscTree
from ..isf.material import Material

BLEND_NAMES = ["Ignore alpha", "Add", "Over", "Over (premultiplied)", "Multiply", "Subtract",
               "Stencil luma*", "Silhouette luma*", "Silhouette alpha*"]


def _color_button(initial: tuple[float, ...], on_change: Callable[[list[float]], None], alpha: bool = True) -> QPushButton:
    btn = QPushButton()
    btn.setFixedWidth(64)

    def paint(c: tuple[float, ...]) -> None:
        q = QColor.fromRgbF(*[float(x) for x in (list(c) + [1.0])[:4]])
        btn.setStyleSheet(f"background-color: {q.name()}; border: 1px solid #555;")
        btn.setProperty("rgba", list(c))

    def pick() -> None:
        cur = btn.property("rgba") or [1, 1, 1, 1]
        q = QColor.fromRgbF(*[float(x) for x in (list(cur) + [1.0])[:4]])
        opts = QColorDialog.ColorDialogOption.ShowAlphaChannel if alpha else QColorDialog.ColorDialogOption(0)
        res = QColorDialog.getColor(q, btn, "Colour", opts)
        if res.isValid():
            rgba = [res.redF(), res.greenF(), res.blueF(), res.alphaF() if alpha else 1.0]
            paint(rgba)
            on_change(rgba)

    paint(initial)
    btn.clicked.connect(pick)
    return btn


class FloatSlider(QWidget):
    """Slider + spin box for a float range."""
    valueChanged = pyqtSignal(float)

    def __init__(self, lo: float, hi: float, value: float, decimals: int = 3, parent: QWidget | None = None):
        super().__init__(parent)
        self.lo, self.hi = float(lo), float(hi)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(decimals)
        self.spin.setRange(self.lo, self.hi)
        self.spin.setSingleStep((self.hi - self.lo) / 100 if self.hi > self.lo else 0.1)
        self.spin.setFixedWidth(80)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.spin)
        self.set_value(value)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)

    def set_value(self, v: float) -> None:
        with QSignalBlocker(self.slider), QSignalBlocker(self.spin):
            self.spin.setValue(float(v))
            self.slider.setValue(self._to_slider(float(v)))

    def _to_slider(self, v: float) -> int:
        if self.hi <= self.lo:
            return 0
        return int(round((v - self.lo) / (self.hi - self.lo) * 1000))

    def _from_slider(self, i: int) -> None:
        v = self.lo + i / 1000 * (self.hi - self.lo)
        with QSignalBlocker(self.spin):
            self.spin.setValue(v)
        self.valueChanged.emit(v)

    def _from_spin(self, v: float) -> None:
        with QSignalBlocker(self.slider):
            self.slider.setValue(self._to_slider(v))
        self.valueChanged.emit(v)


class SurfacesPanel(QWidget):
    selected = pyqtSignal(object)
    changed = pyqtSignal()          # structure changed (add/remove/reorder/visibility)
    action = pyqtSignal(str)        # "add", "duplicate", "delete", "up", "down"

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, key, tip in (("+ Quad", "add", "Add a quad surface"), ("Dup", "duplicate", "Duplicate (Ctrl+D)"),
                               ("Del", "delete", "Delete (Del)"), ("Up", "up", "Bring forward"), ("Down", "down", "Send backward")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=key: self.action.emit(k))
            row.addWidget(b)
        lay.addLayout(row)
        self.project: Project | None = None
        self.list.currentItemChanged.connect(self._on_current)
        self.list.itemChanged.connect(self._on_item_changed)

    def refresh(self, project: Project, selected: QuadSurface | None) -> None:
        self.project = project
        with QSignalBlocker(self.list):
            self.list.clear()
            for s in reversed(project.surfaces):   # top-most first
                it = QListWidgetItem(s.name)
                it.setData(Qt.ItemDataRole.UserRole, s.id)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Checked if s.visible else Qt.CheckState.Unchecked)
                if s.locked:
                    it.setText(s.name + "  (locked)")
                self.list.addItem(it)
                if selected is not None and s.id == selected.id:
                    self.list.setCurrentItem(it)

    def _on_current(self, cur: QListWidgetItem | None, prev: QListWidgetItem | None) -> None:
        if cur is None or self.project is None:
            self.selected.emit(None)
            return
        self.selected.emit(self.project.surface(cur.data(Qt.ItemDataRole.UserRole)))

    def _on_item_changed(self, it: QListWidgetItem) -> None:
        if self.project is None:
            return
        s = self.project.surface(it.data(Qt.ItemDataRole.UserRole))
        if s is not None:
            s.visible = it.checkState() == Qt.CheckState.Checked
            self.changed.emit()


class OutputsPanel(QWidget):
    changed = pyqtSignal()
    selected = pyqtSignal(object)
    fullscreen_requested = pyqtSignal(object, bool)   # Output, fullscreen?
    window_requested = pyqtSignal(object)             # Output (windowed preview)
    action = pyqtSignal(str)                          # "add", "delete"

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, key in (("+ Output", "add"), ("Del", "delete")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, k=key: self.action.emit(k))
            row.addWidget(b)
        lay.addLayout(row)
        self.form_box = QGroupBox("Output")
        form = QFormLayout(self.form_box)
        self.name = QLineEdit()
        self.screen = QComboBox()
        self.width = QSpinBox(); self.width.setRange(16, 16384)
        self.height = QSpinBox(); self.height.setRange(16, 16384)
        self.cx = QDoubleSpinBox(); self.cx.setRange(-1e4, 1e4); self.cx.setDecimals(3)
        self.cy = QDoubleSpinBox(); self.cy.setRange(-1e4, 1e4); self.cy.setDecimals(3)
        self.test = QCheckBox("Show test pattern")
        self.buffer = QCheckBox("Video buffer only (no screen)")
        self.full_btn = QPushButton("Fullscreen on screen (Ctrl+U)")
        self.win_btn = QPushButton("Open as window")
        self.close_btn = QPushButton("Close output window (Ctrl+T)")
        form.addRow("Name", self.name)
        form.addRow("Screen", self.screen)
        size_row = QHBoxLayout(); size_row.addWidget(self.width); size_row.addWidget(QLabel("x")); size_row.addWidget(self.height)
        form.addRow("Pixels", size_row)
        pos_row = QHBoxLayout(); pos_row.addWidget(self.cx); pos_row.addWidget(self.cy)
        form.addRow("Stage centre", pos_row)
        form.addRow(self.test)
        form.addRow(self.buffer)
        form.addRow(self.full_btn)
        form.addRow(self.win_btn)
        form.addRow(self.close_btn)
        lay.addWidget(self.form_box)
        self.project: Project | None = None
        self.current: Output | None = None
        self.list.currentItemChanged.connect(self._on_current)
        self.name.editingFinished.connect(self._apply)
        self.screen.currentIndexChanged.connect(self._apply)
        self.width.valueChanged.connect(self._apply)
        self.height.valueChanged.connect(self._apply)
        self.cx.valueChanged.connect(self._apply)
        self.cy.valueChanged.connect(self._apply)
        self.test.toggled.connect(self._apply)
        self.buffer.toggled.connect(self._apply)
        self.full_btn.clicked.connect(lambda: self.current and self.fullscreen_requested.emit(self.current, True))
        self.win_btn.clicked.connect(lambda: self.current and self.window_requested.emit(self.current))
        self.close_btn.clicked.connect(lambda: self.current and self.fullscreen_requested.emit(self.current, False))
        self._loading = False

    def refresh(self, project: Project, selected: Output | None = None) -> None:
        self.project = project
        with QSignalBlocker(self.list):
            self.list.clear()
            for o in project.outputs:
                it = QListWidgetItem(f"{o.name}  {o.pixel_size[0]}x{o.pixel_size[1]}")
                it.setData(Qt.ItemDataRole.UserRole, o.id)
                self.list.addItem(it)
                if selected is not None and o.id == selected.id:
                    self.list.setCurrentItem(it)
        if selected is None and project.outputs:
            self.list.setCurrentRow(0)
        self._load(selected or (project.outputs[0] if project.outputs else None))

    def _on_current(self, cur: QListWidgetItem | None, prev: QListWidgetItem | None) -> None:
        if cur is None or self.project is None:
            self._load(None)
            return
        o = self.project.output(cur.data(Qt.ItemDataRole.UserRole))
        self._load(o)
        self.selected.emit(o)

    def _load(self, o: Output | None) -> None:
        self.current = o
        self._loading = True
        self.form_box.setEnabled(o is not None)
        if o is not None:
            self.name.setText(o.name)
            self.screen.clear()
            self.screen.addItem("(none)", "")
            for sc in QGuiApplication.screens():
                g = sc.geometry()
                self.screen.addItem(f"{sc.name()}  {g.width()}x{g.height()} @ {g.x()},{g.y()}", sc.name())
                if sc.name() == o.screen_name:
                    self.screen.setCurrentIndex(self.screen.count() - 1)
            self.width.setValue(o.pixel_size[0])
            self.height.setValue(o.pixel_size[1])
            self.cx.setValue(o.centre[0])
            self.cy.setValue(o.centre[1])
            self.test.setChecked(o.test_pattern)
            self.buffer.setChecked(o.is_buffer)
        self._loading = False

    def _apply(self, *_: Any) -> None:
        o = self.current
        if o is None or self._loading:
            return
        o.name = self.name.text().strip() or o.name
        o.screen_name = self.screen.currentData() or ""
        w, h = self.width.value(), self.height.value()
        if (w, h) != o.pixel_size:
            o.pixel_size = (w, h)
            o.size = (3.6 * w / h, 3.6)
        o.centre = (self.cx.value(), self.cy.value())
        o.test_pattern = self.test.isChecked()
        o.is_buffer = self.buffer.isChecked()
        row = self.list.currentRow()
        if row >= 0:
            self.list.item(row).setText(f"{o.name}  {w}x{h}")
        self.changed.emit()


class MediaPanel(QWidget):
    selected = pyqtSignal(object)            # Visual | None
    assign_requested = pyqtSignal(object)    # Visual: assign to the selected surface
    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.add_btn = QToolButton()
        self.add_btn.setText("+ Add")
        self.add_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.add_menu = QMenu(self.add_btn)
        self.add_btn.setMenu(self.add_menu)
        row.addWidget(self.add_btn)
        self.assign_btn = QPushButton("Assign to surface")
        self.assign_btn.setToolTip("Use this media on the selected surface (also: double-click)")
        row.addWidget(self.assign_btn)
        self.remove_btn = QPushButton("Remove")
        row.addWidget(self.remove_btn)
        lay.addLayout(row)
        self.project: Project | None = None
        self.list.currentItemChanged.connect(self._on_current)
        self.list.itemDoubleClicked.connect(lambda it: self._emit_assign())
        self.assign_btn.clicked.connect(self._emit_assign)
        self.on_add: Callable[[str, str], None] = lambda kind, arg: None
        self._build_menu()
        self.remove_btn.clicked.connect(self._remove)

    def _build_menu(self) -> None:
        m = self.add_menu
        m.clear()
        m.addAction("Image file...", lambda: self.on_add("image", ""))
        m.addAction("Movie file...", lambda: self.on_add("movie", ""))
        m.addAction("Material folder or .fs...", lambda: self.on_add("material", ""))
        m.addSeparator()
        m.addAction("Solid colour", lambda: self.on_add("solid", ""))
        m.addAction("Test card", lambda: self.on_add("test_card", ""))
        m.addAction("Output loopback (video buffer)", lambda: self.on_add("loopback", ""))
        lib = self._library_materials()
        if lib:
            m.addSeparator()
            sub = m.addMenu("MadMapper library material")
            for folder in lib:
                sub.addAction(folder.name, lambda _=False, f=folder: self.on_add("material", str(f)))

    @staticmethod
    def _library_materials() -> list[Path]:
        for base in MADMAPPER_LIBRARY_CANDIDATES:
            d = base / "Materials"
            if d.is_dir():
                return sorted(p for p in d.iterdir() if p.is_dir() and any(p.glob("*.fs")))
        return []

    def refresh(self, project: Project, selected: Visual | None = None) -> None:
        self.project = project
        with QSignalBlocker(self.list):
            self.list.clear()
            for v in project.visuals:
                it = QListWidgetItem(f"{v.name}   [{v.kind.value}]")
                it.setData(Qt.ItemDataRole.UserRole, v.id)
                it.setToolTip(v.source)
                self.list.addItem(it)
                if selected is not None and v.id == selected.id:
                    self.list.setCurrentItem(it)

    def current_visual(self) -> Visual | None:
        it = self.list.currentItem()
        if it is None or self.project is None:
            return None
        return self.project.visual(it.data(Qt.ItemDataRole.UserRole))

    def _on_current(self, cur: QListWidgetItem | None, prev: QListWidgetItem | None) -> None:
        self.selected.emit(self.current_visual())

    def _emit_assign(self) -> None:
        v = self.current_visual()
        if v is not None:
            self.assign_requested.emit(v)

    def _remove(self) -> None:
        v = self.current_visual()
        if v is not None and self.project is not None:
            self.project.remove_visual(v.id)
            self.changed.emit()


class Inspector(QScrollArea):
    """Property editor for the selected surface and its (or the selected) visual."""
    surface_changed = pyqtSignal()
    visual_changed = pyqtSignal(object)   # Visual

    mask_edit_toggled = pyqtSignal(bool)

    def __init__(self, engine: RenderEngine, parent: QWidget | None = None):
        super().__init__(parent)
        self.engine = engine
        self.mask_editing = False
        self.setWidgetResizable(True)
        self.body = QWidget()
        self.layout_ = QVBoxLayout(self.body)
        self.layout_.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setWidget(self.body)
        self.surface: QuadSurface | None = None
        self.visual: Visual | None = None
        self.setMinimumWidth(300)

    def show_items(self, surface: QuadSurface | None, visual: Visual | None) -> None:
        self.surface, self.visual = surface, visual
        self.rebuild()

    def rebuild(self) -> None:
        while self.layout_.count():
            item = self.layout_.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if self.surface is not None:
            self.layout_.addWidget(self._surface_box(self.surface))
        if self.visual is not None:
            self.layout_.addWidget(self._visual_box(self.visual))
        if self.surface is None and self.visual is None:
            self.layout_.addWidget(QLabel("Select a surface or a media item."))

    # ---- surface ----
    def _surface_box(self, s: QuadSurface) -> QGroupBox:
        box = QGroupBox(f"{s.shape.value.capitalize()} surface: {s.name}")
        form = QFormLayout(box)
        name = QLineEdit(s.name)

        def set_name() -> None:
            s.name = name.text().strip() or s.name
            box.setTitle(f"Surface: {s.name}")
            self.surface_changed.emit()
        name.editingFinished.connect(set_name)
        form.addRow("Name", name)
        vis = QCheckBox("Visible"); vis.setChecked(s.visible)
        vis.toggled.connect(lambda v: (setattr(s, "visible", v), self.surface_changed.emit()))
        lock = QCheckBox("Locked"); lock.setChecked(s.locked)
        lock.toggled.connect(lambda v: (setattr(s, "locked", v), self.surface_changed.emit()))
        row = QHBoxLayout(); row.addWidget(vis); row.addWidget(lock)
        form.addRow(row)
        op = FloatSlider(0.0, 1.0, s.opacity)
        op.valueChanged.connect(lambda v: (setattr(s, "opacity", v), self.surface_changed.emit()))
        form.addRow("Opacity", op)
        blend = QComboBox(); blend.addItems(BLEND_NAMES); blend.setCurrentIndex(int(s.blend_mode))
        blend.setToolTip("* stencil/silhouette modes are drawn as 'Over' in this version")
        blend.currentIndexChanged.connect(lambda i: (setattr(s, "blend_mode", BlendMode(i)), self.surface_changed.emit()))
        form.addRow("Blend mode", blend)
        col = _color_button(s.color, lambda c: (setattr(s, "color", (c[0], c[1], c[2])), self.surface_changed.emit()), alpha=False)
        form.addRow("Colour", col)
        persp = QCheckBox("Perspective corner pin"); persp.setChecked(s.perspective)
        persp.toggled.connect(lambda v: (setattr(s, "perspective", v), self.surface_changed.emit()))
        form.addRow(persp)
        fh = QCheckBox("Flip H"); fh.setChecked(s.flip_h)
        fh.toggled.connect(lambda v: (setattr(s, "flip_h", v), self.surface_changed.emit()))
        fv = QCheckBox("Flip V"); fv.setChecked(s.flip_v)
        fv.toggled.connect(lambda v: (setattr(s, "flip_v", v), self.surface_changed.emit()))
        row2 = QHBoxLayout(); row2.addWidget(fh); row2.addWidget(fv)
        form.addRow(row2)

        se_box = QGroupBox("Soft edge")
        se_box.setCheckable(True)
        se_box.setChecked(s.soft_edge.active)
        se_box.toggled.connect(lambda v: (setattr(s.soft_edge, "active", v), self.surface_changed.emit()))
        se_form = QFormLayout(se_box)
        for label, attr in (("Left", "left"), ("Right", "right"), ("Top", "top"), ("Bottom", "bottom")):
            sl = FloatSlider(0.0, 1.0, getattr(s.soft_edge, attr))
            sl.valueChanged.connect(lambda v, a=attr: (setattr(s.soft_edge, a, v), self.surface_changed.emit()))
            se_form.addRow(label, sl)
        for label, attr in (("Left curve", "left_curve"), ("Right curve", "right_curve"), ("Top curve", "top_curve"), ("Bottom curve", "bottom_curve")):
            sl = FloatSlider(0.0, 1.0, getattr(s.soft_edge, attr))
            sl.valueChanged.connect(lambda v, a=attr: (setattr(s.soft_edge, a, v), self.surface_changed.emit()))
            se_form.addRow(label, sl)
        gamma = FloatSlider(0.2, 4.0, s.soft_edge.gamma)
        gamma.valueChanged.connect(lambda v: (setattr(s.soft_edge, "gamma", v), self.surface_changed.emit()))
        se_form.addRow("Gamma", gamma)
        if s.shape != Shape.MASK:
            form.addRow(se_box)

        if s.shape in (Shape.QUAD, Shape.CIRCLE):
            mask_box = QGroupBox("Layer mask")
            mf = QFormLayout(mask_box)
            edit_btn = QPushButton("Edit mask in input view" if not self.mask_editing else "Stop editing mask")
            edit_btn.setCheckable(True)
            edit_btn.setChecked(self.mask_editing)

            def toggle_edit(on: bool) -> None:
                if on and len(s.mask_points) < 3:
                    s.mask_points = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)]
                    self.surface_changed.emit()
                self.mask_editing = on
                edit_btn.setText("Stop editing mask" if on else "Edit mask in input view")
                self.mask_edit_toggled.emit(on)
            edit_btn.toggled.connect(toggle_edit)
            mf.addRow(edit_btn)
            inv = QCheckBox("Invert (cut a hole)"); inv.setChecked(s.mask_inverted)
            inv.toggled.connect(lambda v: (setattr(s, "mask_inverted", v), self.surface_changed.emit()))
            mf.addRow(inv)
            feather = FloatSlider(0.0, 0.25, s.mask_feather)
            feather.valueChanged.connect(lambda v: (setattr(s, "mask_feather", v), self.surface_changed.emit()))
            mf.addRow("Feather", feather)
            clear = QPushButton("Remove mask")

            def clear_mask() -> None:
                s.mask_points = []
                if self.mask_editing:
                    edit_btn.setChecked(False)
                self.surface_changed.emit()
            clear.clicked.connect(clear_mask)
            mf.addRow(clear)
            form.addRow(mask_box)

        warp_box = QGroupBox("Mesh warp")
        wf = QFormLayout(warp_box)
        cols = QSpinBox(); cols.setRange(1, 32); cols.setValue(s.warp_cols or 4)
        rows = QSpinBox(); rows.setRange(1, 32); rows.setValue(s.warp_rows or 4)
        wrow = QHBoxLayout(); wrow.addWidget(cols); wrow.addWidget(QLabel("x")); wrow.addWidget(rows)
        wf.addRow("Grid", wrow)
        smooth = QCheckBox("Smooth (spline through the nodes)"); smooth.setChecked(s.warp_smooth)
        smooth.toggled.connect(lambda v: (setattr(s, "warp_smooth", v), self.surface_changed.emit()))
        wf.addRow(smooth)
        en = QPushButton("Enable / reset grid")

        def enable_warp() -> None:
            from ..render.geometry import bilinear_grid
            s.warp_cols, s.warp_rows = cols.value(), rows.value()
            s.warp_points = bilinear_grid(s.corners, s.warp_cols, s.warp_rows)
            self.surface_changed.emit()
        en.clicked.connect(enable_warp)
        dis = QPushButton("Disable")

        def disable_warp() -> None:
            s.warp_points = []
            s.warp_cols = s.warp_rows = 0
            self.surface_changed.emit()
        dis.clicked.connect(disable_warp)
        brow = QHBoxLayout(); brow.addWidget(en); brow.addWidget(dis)
        wf.addRow(brow)
        if s.shape in (Shape.QUAD, Shape.CIRCLE):
            form.addRow(warp_box)
        if s.shape != Shape.MASK:
            form.addRow(self._fx_box(s))
        return box

    def _fx_box(self, s: QuadSurface) -> QGroupBox:
        box = QGroupBox("Surface FX")
        form = QFormLayout(box)
        combo = QComboBox()
        names = library_fx_names()
        combo.addItem("(none)", "")
        current_label = Path(s.fx_name).name if s.fx_name else ""
        for n in names:
            combo.addItem(n, n)
        if s.fx_name and current_label not in names:
            combo.addItem(current_label + " (project)", s.fx_name)
        idx = combo.findData(s.fx_name) if s.fx_name else 0
        combo.setCurrentIndex(max(0, idx))

        def choose(i: int) -> None:
            name = combo.itemData(i) or ""
            if name != s.fx_name:
                s.fx_name = name
                s.fx_params = {}
                s.fx_active = bool(name)
                self.surface_changed.emit()
                self.rebuild()
        combo.currentIndexChanged.connect(choose)
        form.addRow("FX", combo)
        active = QCheckBox("Active"); active.setChecked(s.fx_active)
        active.toggled.connect(lambda v: (setattr(s, "fx_active", v), self.surface_changed.emit()))
        form.addRow(active)
        if s.fx_active and s.fx_name:
            fx = self.engine.fx_for(s)
            if fx is None:
                lab = QLabel(f"FX folder not found: {s.fx_name}"); lab.setStyleSheet("color: #ff7a60;"); lab.setWordWrap(True)
                form.addRow(lab)
            else:
                if fx.error:
                    err = QLabel(fx.error); err.setStyleSheet("color: #ff7a60;"); err.setWordWrap(True)
                    form.addRow(err)
                if fx.material is not None:
                    def setter(name: str, value: Any, mat: Material = fx.material) -> None:
                        mat.set_value(name, value)
                        s.fx_params[name] = mat.values[name]
                        self.surface_changed.emit()
                    self._isf_params(form, fx.material, setter)
        return box

    # ---- visual ----
    def _visual_box(self, v: Visual) -> QGroupBox:
        box = QGroupBox(f"Media: {v.name}  [{v.kind.value}]")
        form = QFormLayout(box)
        name = QLineEdit(v.name)

        def set_name() -> None:
            v.name = name.text().strip() or v.name
            box.setTitle(f"Media: {v.name}  [{v.kind.value}]")
            self.visual_changed.emit(v)
        name.editingFinished.connect(set_name)
        form.addRow("Name", name)
        src = self.engine.sources.get(v.id)
        if v.kind in (VisualKind.IMAGE, VisualKind.MOVIE, VisualKind.MATERIAL):
            path = QLabel(v.source)
            path.setWordWrap(True)
            path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow("Source", path)
        if src is not None and src.error:
            err = QLabel(src.error)
            err.setStyleSheet("color: #ff7a60;")
            err.setWordWrap(True)
            form.addRow("Error", err)
        if v.kind == VisualKind.MOVIE:
            loop = QCheckBox("Loop"); loop.setChecked(v.loop)
            loop.toggled.connect(lambda b: (setattr(v, "loop", b), self._apply_attrs(v)))
            form.addRow(loop)
            speed = FloatSlider(0.1, 4.0, v.speed, 2)
            speed.valueChanged.connect(lambda x: (setattr(v, "speed", x), self._apply_attrs(v)))
            form.addRow("Speed", speed)
        elif v.kind == VisualKind.SOLID:
            col = _color_button(v.attributes.get("color", [1, 1, 1, 1]), lambda c: (v.attributes.__setitem__("color", c), self._apply_attrs(v)))
            form.addRow("Colour", col)
        elif v.kind == VisualKind.TEST_CARD:
            for key, label in (("divisions_x", "Divisions X"), ("divisions_y", "Divisions Y")):
                sp = QSpinBox(); sp.setRange(1, 64); sp.setValue(int(v.attributes.get(key, 8)))
                sp.valueChanged.connect(lambda x, k=key: (v.attributes.__setitem__(k, x), self._apply_attrs(v)))
                form.addRow(label, sp)
            for key, label in (("front_color", "Front colour"), ("back_color", "Back colour")):
                col = _color_button(v.attributes.get(key, [1, 1, 1, 1] if key == "front_color" else [0, 0, 0, 1]),
                                    lambda c, k=key: (v.attributes.__setitem__(k, c), self._apply_attrs(v)))
                form.addRow(label, col)
            circ = QCheckBox("Centre circle"); circ.setChecked(bool(v.attributes.get("show_circle", True)))
            circ.toggled.connect(lambda b: (v.attributes.__setitem__("show_circle", b), self._apply_attrs(v)))
            form.addRow(circ)
        elif v.kind == VisualKind.MATERIAL and isinstance(src, MaterialSourceGL) and src.material is not None:
            self._material_params(form, v, src)
        if v.kind in (VisualKind.MATERIAL, VisualKind.TEST_CARD):
            rw = QSpinBox(); rw.setRange(16, 8192); rw.setValue(v.render_width)
            rh = QSpinBox(); rh.setRange(16, 8192); rh.setValue(v.render_height)
            rw.valueChanged.connect(lambda x: (setattr(v, "render_width", x), self._apply_attrs(v)))
            rh.valueChanged.connect(lambda x: (setattr(v, "render_height", x), self._apply_attrs(v)))
            row = QHBoxLayout(); row.addWidget(rw); row.addWidget(QLabel("x")); row.addWidget(rh)
            form.addRow("Render size", row)
        return box

    def _apply_attrs(self, v: Visual) -> None:
        src = self.engine.sources.get(v.id)
        if src is not None:
            src.apply_attributes()
        self.visual_changed.emit(v)

    def _material_params(self, form: QFormLayout, v: Visual, src: MaterialSourceGL) -> None:
        mat = src.material
        assert mat is not None
        self._isf_params(form, mat, lambda name, val: self._set_param(src, v, name, val))

    def _isf_params(self, form: QFormLayout, mat: Material, setter: Callable[[str, Any], None]) -> None:
        meta = []
        if mat.doc.description:
            meta.append(mat.doc.description)
        if mat.doc.credit:
            meta.append("by " + mat.doc.credit)
        if meta:
            lab = QLabel(" - ".join(meta)); lab.setWordWrap(True); lab.setStyleSheet("color: #aaa;")
            form.addRow(lab)
        restart = QPushButton("Restart time")
        restart.clicked.connect(mat.restart)
        form.addRow(restart)
        groups: dict[str, QFormLayout] = {}
        ordered = sorted(mat.inputs, key=lambda i: (i.order_index if i.order_index >= 0 else 10_000))
        for inp in ordered:
            if inp.internal or inp.is_texture or inp.type in (InputType.AUDIO, InputType.AUDIO_FFT, InputType.STRING,
                                                                InputType.CURVE, InputType.FLOAT_VECTOR, InputType.INT_VECTOR,
                                                                InputType.STRING_VECTOR, InputType.MAT4):
                continue
            g = inp.group
            if g not in groups:
                gb = QGroupBox(g) if g else None
                gf = QFormLayout(gb) if gb else form
                if gb is not None:
                    form.addRow(gb)
                groups[g] = gf
            target = groups[g]
            w = self._param_widget(inp, mat.values.get(inp.name, inp.default), lambda val, n=inp.name: setter(n, val))
            if w is not None:
                if inp.description:
                    w.setToolTip(inp.description)
                if inp.type in (InputType.BOOL, InputType.EVENT):
                    target.addRow(w)
                else:
                    target.addRow(inp.short_label, w)

    def _set_param(self, src: MaterialSourceGL, v: Visual, name: str, value: Any) -> None:
        src.set_parameter(name, value)
        self.visual_changed.emit(v)

    def _param_widget(self, inp: IsfInput, value: Any, on_change: Callable[[Any], None]) -> QWidget | None:
        t = inp.type
        if t == InputType.FLOAT:
            lo = inp.min if inp.min is not None and inp.min > -1e30 else -10.0
            hi = inp.max if inp.max is not None and inp.max < 1e30 else 10.0
            w = FloatSlider(lo, hi, float(value))
            w.valueChanged.connect(on_change)
            return w
        if t == InputType.INT:
            w = QSpinBox()
            w.setRange(int(max(inp.min, -2**31)) if inp.min is not None else -10**6, int(min(inp.max, 2**31 - 1)) if inp.max is not None else 10**6)
            w.setValue(int(value))
            w.valueChanged.connect(on_change)
            return w
        if t in (InputType.BOOL, InputType.EVENT):
            w = QCheckBox(inp.short_label)
            w.setChecked(bool(value))
            w.toggled.connect(on_change)
            return w
        if t == InputType.LONG:
            w = QComboBox()
            w.addItems(inp.labels)
            w.setCurrentIndex(int(value) if isinstance(value, (int, float)) else inp.long_index(value))
            w.currentIndexChanged.connect(on_change)
            return w
        if t == InputType.COLOR:
            return _color_button(value if isinstance(value, (list, tuple)) else inp.default, on_change, alpha="no_alpha" not in inp.flags)
        if t in (InputType.POINT2D, InputType.FLOAT_RANGE):
            box = QWidget()
            lay = QHBoxLayout(box); lay.setContentsMargins(0, 0, 0, 0)
            spins = []
            for k in range(2):
                sp = QDoubleSpinBox(); sp.setDecimals(3)
                lo = (inp.min[k] if isinstance(inp.min, list) else inp.min) if inp.min is not None else -1e4
                hi = (inp.max[k] if isinstance(inp.max, list) else inp.max) if inp.max is not None else 1e4
                sp.setRange(float(lo), float(hi)); sp.setSingleStep(0.01)
                sp.setValue(float(value[k]))
                lay.addWidget(sp)
                spins.append(sp)
            for sp in spins:
                sp.valueChanged.connect(lambda _x: on_change([s.value() for s in spins]))
            return box
        if t in (InputType.POINT3D, InputType.POINT4D):
            n = 3 if t == InputType.POINT3D else 4
            box = QWidget()
            lay = QHBoxLayout(box); lay.setContentsMargins(0, 0, 0, 0)
            spins = []
            for k in range(n):
                sp = QDoubleSpinBox(); sp.setDecimals(3); sp.setRange(-1e4, 1e4); sp.setSingleStep(0.01)
                sp.setValue(float(value[k]))
                lay.addWidget(sp)
                spins.append(sp)
            for sp in spins:
                sp.valueChanged.connect(lambda _x: on_change([s.value() for s in spins]))
            return box
        return None


class OscPanel(QWidget):
    """OSC server control: enable, port, feedback target, address reference and a message log."""
    settings_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        row = QHBoxLayout()
        self.enabled = QCheckBox("Receive OSC on UDP port")
        self.port = QSpinBox(); self.port.setRange(1024, 65535); self.port.setValue(8010)
        row.addWidget(self.enabled); row.addWidget(self.port); row.addStretch(1)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Feedback to"))
        self.fb_host = QLineEdit(); self.fb_host.setPlaceholderText("host (empty = reply to sender)")
        self.fb_port = QSpinBox(); self.fb_port.setRange(0, 65535)
        row2.addWidget(self.fb_host, 1); row2.addWidget(self.fb_port)
        lay.addLayout(row2)
        self.status = QLabel("OSC off")
        lay.addWidget(self.status)
        self.log = QListWidget()
        self.log.setMaximumHeight(140)
        lay.addWidget(self.log)
        self.addresses = QListWidget()
        for e in OscTree.documentation():
            it = QListWidgetItem(f"{e.pattern}   [{e.kind}]  {e.doc}")
            it.setToolTip("f: float, b: bool (0/1), i: int, s: string, n: no argument, v: value(s). "
                          "<sel> = selected, an id, or a name (spaces as _). A message without arguments queries the value.")
            self.addresses.addItem(it)
        lay.addWidget(QLabel("Addresses"))
        lay.addWidget(self.addresses, 1)
        for w in (self.enabled.toggled, self.port.valueChanged, self.fb_host.editingFinished, self.fb_port.valueChanged):
            w.connect(lambda *_: self.settings_changed.emit())

    def load(self, project: Project) -> None:
        with QSignalBlocker(self.enabled), QSignalBlocker(self.port), QSignalBlocker(self.fb_host), QSignalBlocker(self.fb_port):
            self.enabled.setChecked(project.osc_enabled)
            self.port.setValue(project.osc_port)
            self.fb_host.setText(project.osc_feedback_host)
            self.fb_port.setValue(project.osc_feedback_port)

    def store(self, project: Project) -> None:
        project.osc_enabled = self.enabled.isChecked()
        project.osc_port = self.port.value()
        project.osc_feedback_host = self.fb_host.text().strip()
        project.osc_feedback_port = self.fb_port.value()

    def add_log(self, text: str) -> None:
        self.log.addItem(text)
        while self.log.count() > 200:
            self.log.takeItem(0)
        self.log.scrollToBottom()
