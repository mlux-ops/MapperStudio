"""Media sources that turn a `Visual` into a GL texture each frame."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtGui import QImage, QColor
from PyQt6.QtMultimedia import QMediaPlayer, QVideoSink, QVideoFrame, QAudioOutput
from PyQt6.QtOpenGL import QOpenGLTexture

from ..model import Visual, VisualKind
from ..isf import Material, load_material, IsfError
from ..isf.header import parse_isf_source
from ..isf.material import MaterialSource
from .gl import StreamingTexture, TextureRef, texture_from_qimage
from .materials import MaterialRenderer

BUILTIN_DIR = Path(__file__).resolve().parent / "builtin"


class MediaSource(QObject):
    """Base class. `prepare()` is called each frame with a GL context current."""
    changed = pyqtSignal()

    def __init__(self, visual: Visual):
        super().__init__()
        self.visual = visual
        self.error: str | None = None

    def prepare(self, bpm: float) -> None:
        pass

    def texture(self) -> TextureRef | None:
        return None

    def destroy(self) -> None:
        pass

    def apply_attributes(self) -> None:
        """Push `visual.attributes` into the source (materials: parameter values)."""


class ImageSource(MediaSource):
    def __init__(self, visual: Visual):
        super().__init__(visual)
        self._tex: QOpenGLTexture | None = None
        self._loaded = False

    def prepare(self, bpm: float) -> None:
        if self._loaded:
            return
        self._loaded = True
        img = QImage(self.visual.source)
        if img.isNull():
            self.error = f"cannot load image {self.visual.source}"
            return
        self._tex = texture_from_qimage(img, mipmaps=True)

    def texture(self) -> TextureRef | None:
        if self._tex is None:
            return None
        return TextureRef(self._tex.textureId(), self._tex.width(), self._tex.height())

    def destroy(self) -> None:
        if self._tex is not None:
            self._tex.destroy()
            self._tex = None


class MovieSource(MediaSource):
    """Video decoded by Qt Multimedia; the latest frame is uploaded to a streaming texture."""

    def __init__(self, visual: Visual):
        super().__init__(visual)
        self.player = QMediaPlayer()
        self.sink = QVideoSink()
        self.audio = QAudioOutput()
        self.audio.setMuted(True)
        self.player.setVideoSink(self.sink)
        self.player.setAudioOutput(self.audio)
        self.player.setLoops(QMediaPlayer.Loops.Infinite if visual.loop else 1)
        self.player.setPlaybackRate(visual.speed or 1.0)
        self.player.errorOccurred.connect(self._on_error)
        self._pending: QImage | None = None
        self.sink.videoFrameChanged.connect(self._on_frame)
        self._stream = StreamingTexture()
        src = Path(visual.source)
        if not src.exists():
            self.error = f"movie file missing: {src}"
        else:
            self.player.setSource(QUrl.fromLocalFile(str(src)))
            self.player.play()

    def _on_error(self, err: QMediaPlayer.Error, text: str) -> None:
        self.error = text or str(err)

    def _on_frame(self, frame: QVideoFrame) -> None:
        # Convert immediately: a stored QVideoFrame's buffer is recycled by the decoder and a
        # deferred toImage() crashes (observed with Qt 6.11 / FFmpeg backend on Windows).
        # Conversion costs ~5 ms per 1080p frame, so when the previous image has not been consumed
        # yet (the UI runs slower than the video) the new frame is dropped instead of converted.
        if frame.isValid() and self._pending is None:
            img = frame.toImage()
            if not img.isNull():
                self._pending = img

    def prepare(self, bpm: float) -> None:
        img = self._pending
        if img is None:
            return
        self._pending = None
        self._stream.update(img)

    def texture(self) -> TextureRef | None:
        if self._stream.texture is None:
            return None
        return TextureRef(self._stream.texture_id, self._stream.width, self._stream.height)

    def apply_attributes(self) -> None:
        self.player.setLoops(QMediaPlayer.Loops.Infinite if self.visual.loop else 1)
        self.player.setPlaybackRate(self.visual.speed or 1.0)

    def destroy(self) -> None:
        self.player.stop()
        self.player.setVideoSink(None)
        self._stream.destroy()


class MaterialSourceGL(MediaSource):
    """An ISF material rendered to a texture of the visual's render size."""

    def __init__(self, visual: Visual, material: Material | None = None):
        super().__init__(visual)
        self.material: Material | None = material
        self.renderer: MaterialRenderer | None = None
        if self.material is None:
            try:
                self.material = load_material(visual.source)
            except (IsfError, OSError) as exc:
                self.error = str(exc)
                return
        self.apply_attributes()
        self.renderer = MaterialRenderer(self.material, visual.render_width, visual.render_height)

    def apply_attributes(self) -> None:
        if self.material is None:
            return
        attrs = self.visual.attributes
        by_label = bool(attrs.get("__by_label__"))
        missing = self.material.apply_values(attrs, by_label=by_label)
        if by_label:
            # Convert the imported label-keyed values to name-keyed ones so the inspector edits them.
            self.visual.attributes = {i.name: self.material.values[i.name] for i in self.material.inputs}
        elif missing:
            for k in missing:
                attrs.pop(k, None)
        if self.renderer is not None:
            self.renderer.resize(self.visual.render_width, self.visual.render_height)

    def set_parameter(self, name: str, value) -> None:
        if self.material is None:
            return
        self.material.set_value(name, value)
        self.visual.attributes[name] = self.material.values[name]

    def prepare(self, bpm: float) -> None:
        if self.renderer is None:
            return
        if self.material is not None and self.material.source_changed_on_disk():
            self.material.mtime = self.material.source.fragment_path.stat().st_mtime
            self.renderer.reload_source()
            self.material = self.renderer.material
        self.renderer.render(bpm)
        self.error = self.renderer.error

    def texture(self) -> TextureRef | None:
        return self.renderer.texture() if self.renderer else None

    def destroy(self) -> None:
        if self.renderer is not None:
            self.renderer.destroy()
            self.renderer = None


def _builtin_material(name: str) -> Material:
    path = BUILTIN_DIR / name / f"{name}.fs"
    text = path.read_text(encoding="utf-8")
    doc = parse_isf_source(text)
    return Material(MaterialSource(path.parent, path, None, None, name), doc)


class TestCardSource(MaterialSourceGL):
    """Built-in test card (a MapStudio material in `render/builtin/TestCard`)."""

    def __init__(self, visual: Visual):
        material = _builtin_material("TestCard")
        super().__init__(visual, material)

    def apply_attributes(self) -> None:
        if self.material is None:
            return
        a = self.visual.attributes
        self.material.set_value("divisions_x", int(a.get("divisions_x", 8)))
        self.material.set_value("divisions_y", int(a.get("divisions_y", 8)))
        self.material.set_value("front_color", a.get("front_color", [1, 1, 1, 1]))
        self.material.set_value("back_color", a.get("back_color", [0, 0, 0, 1]))
        self.material.set_value("show_circle", bool(a.get("show_circle", True)))
        if self.renderer is not None:
            self.renderer.resize(self.visual.render_width, self.visual.render_height)


class SolidSource(MaterialSourceGL):
    """Built-in solid colour."""

    def __init__(self, visual: Visual):
        material = _builtin_material("SolidColor")
        super().__init__(visual, material)

    def apply_attributes(self) -> None:
        if self.material is None:
            return
        self.material.set_value("color", self.visual.attributes.get("color", [1, 1, 1, 1]))
        if self.renderer is not None:
            self.renderer.resize(64, 64)


class LoopbackSource(MediaSource):
    """The rendered frame of another output (a video buffer)."""

    def __init__(self, visual: Visual):
        super().__init__(visual)
        try:
            self.output_id = int(visual.source)
        except ValueError:
            self.output_id = -1
            self.error = "loopback visual without an output id"
        self.ref: TextureRef | None = None

    def texture(self) -> TextureRef | None:
        return self.ref


def create_source(visual: Visual) -> MediaSource:
    if visual.kind == VisualKind.IMAGE:
        return ImageSource(visual)
    if visual.kind == VisualKind.MOVIE:
        return MovieSource(visual)
    if visual.kind == VisualKind.MATERIAL:
        return MaterialSourceGL(visual)
    if visual.kind == VisualKind.TEST_CARD:
        return TestCardSource(visual)
    if visual.kind == VisualKind.SOLID:
        return SolidSource(visual)
    if visual.kind == VisualKind.OUTPUT_LOOPBACK:
        return LoopbackSource(visual)
    raise ValueError(f"unknown visual kind {visual.kind}")


def qcolor_from_rgba(rgba) -> QColor:
    r, g, b, a = (list(rgba) + [1.0])[:4]
    return QColor.fromRgbF(float(r), float(g), float(b), float(a))
