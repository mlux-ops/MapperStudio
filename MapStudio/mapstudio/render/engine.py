"""The render engine: owns media sources and draws the stage into any GL target.

Per frame (`frame()`, called from the UI timer with the engine's own offscreen context current):
  1. every media source prepares its texture (materials render, movies upload a frame);
  2. every output that is used as a loopback source is rendered into its own FBO.
Views (stage preview, input view, output windows) then call `draw_stage()` from their own
contexts; textures are shared between contexts, VAOs are created per context.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PyQt6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
from PyQt6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLShaderProgram

from PyQt6.QtGui import QImage, QPainter, QPolygonF, QColor
from PyQt6.QtCore import QPointF
from PyQt6.QtOpenGL import QOpenGLTexture

from ..model import Project, QuadSurface, Output, Visual, VisualKind, BlendMode, Shape
from .geometry import (projective_texcoords, affine_texcoords, grid_triangles, quad_from_grid, smooth_grid,
                       triangulate_polygon, homography_unit_square_to_quad)
from .gl import texture_from_qimage
from .gl import (
    DynamicMesh, build_program, gl_funcs, make_fbo, TextureRef, GL_BLEND, GL_DEPTH_TEST, GL_SCISSOR_TEST,
    GL_COLOR_BUFFER_BIT, GL_ONE, GL_ZERO, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_DST_COLOR,
    GL_ONE_MINUS_SRC_COLOR, GL_FUNC_ADD, GL_FUNC_REVERSE_SUBTRACT, GL_TEXTURE0, GL_TEXTURE_2D,
)
from .media import MediaSource, LoopbackSource, create_source
from .fx import FxRenderer, find_fx_folder
from ..isf.fx import COMPOSITE_GLSL
from PyQt6.QtGui import QMatrix4x4

SURFACE_VERTEX = """#version 150 core
uniform mat3 view;            // stage -> clip space (2D)
in vec2 position;             // stage space
in vec3 texcoord;             // (u*q, v*q, q) projective texture coordinates
in vec2 localcoord;           // 0..1 across the surface for soft-edge
out vec3 v_tc;
out vec2 v_local;
void main() {
    vec3 p = view * vec3(position, 1.0);
    gl_Position = vec4(p.xy, 0.0, 1.0);
    v_tc = texcoord;
    v_local = localcoord;
}
"""

SURFACE_FRAGMENT = """#version 150 core
uniform sampler2D tex;
uniform int flipMode;         // bit0 flip h, bit1 flip v, bit2 texture stored top-down
uniform int hasTexture;       // 0: no media; 1: media bound; 2: no media, draw the editor placeholder; 3: solid black (mask surface)
in vec3 v_tc;
in vec2 v_local;
out vec4 FragColor;
""" + COMPOSITE_GLSL + """
void main() {
    vec2 uv = v_tc.xy / max(v_tc.z, 1e-6);
    if ((flipMode & 1) != 0) uv.x = 1.0 - uv.x;
    if ((flipMode & 2) != 0) uv.y = 1.0 - uv.y;
    if ((flipMode & 4) != 0) uv.y = 1.0 - uv.y;
    // Input geometry outside the media is transparent (the media is not repeated or stretched).
    if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) discard;
    if (hasTexture == 0) discard;
    vec4 c = hasTexture == 1 ? texture(tex, uv) : (hasTexture == 3 ? vec4(0.0, 0.0, 0.0, 1.0) : vec4(0.25, 0.25, 0.25, 1.0));
    if (!mm_composite(c, v_local, 1.0)) discard;
    FragColor = c;
}
"""

TEST_PATTERN_FRAGMENT = """#version 150 core
uniform vec2 size;
in vec3 v_tc;
in vec2 v_local;
out vec4 FragColor;
void main() {
    vec2 uv = v_local;
    vec2 px = 1.0 / size;
    float g = 0.0;
    vec2 f = fract(uv * 8.0);
    float d = min(min(f.x, 1.0 - f.x), min(f.y, 1.0 - f.y)) / 8.0;
    g = 1.0 - smoothstep(0.0, 2.0 * px.x, d);
    vec2 c = uv - 0.5;
    float circ = 1.0 - smoothstep(0.0, 2.0 * px.x, abs(length(vec2(c.x * size.x / size.y, c.y)) - 0.4));
    vec3 col = mix(vec3(0.08, 0.1, 0.14), vec3(1.0), max(g, circ));
    FragColor = vec4(col, 1.0);
}
"""


@dataclass
class ViewRect:
    """A rectangle of stage space to show (left, bottom, right, top)."""
    left: float
    bottom: float
    right: float
    top: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.top - self.bottom

    def matrix(self) -> np.ndarray:
        """3x3 stage -> clip space."""
        sx = 2.0 / max(self.width, 1e-9)
        sy = 2.0 / max(self.height, 1e-9)
        return np.array([[sx, 0, -1 - self.left * sx], [0, sy, -1 - self.bottom * sy], [0, 0, 1]], dtype=np.float32)

    @classmethod
    def for_output(cls, o: Output) -> "ViewRect":
        l, b, r, t = o.rect()
        return cls(l, b, r, t)

    def fit_aspect(self, aspect: float) -> "ViewRect":
        """Expand so the rect has the given width/height aspect, keeping the centre."""
        cx, cy = (self.left + self.right) / 2, (self.bottom + self.top) / 2
        w, h = self.width, self.height
        if w / max(h, 1e-9) < aspect:
            w = h * aspect
        else:
            h = w / aspect
        return ViewRect(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


class ContextResources:
    """Per-context GL objects (VAOs cannot be shared)."""

    def __init__(self, program: QOpenGLShaderProgram, test_program: QOpenGLShaderProgram):
        self.mesh = DynamicMesh(program, [("position", 2), ("texcoord", 3), ("localcoord", 2)])
        self.test_mesh = DynamicMesh(test_program, [("position", 2), ("texcoord", 3), ("localcoord", 2)])

    def destroy(self) -> None:
        self.mesh.destroy()
        self.test_mesh.destroy()


class RenderEngine:
    def __init__(self, project: Project):
        self.project = project
        self.sources: dict[int, MediaSource] = {}
        self.output_fbos: dict[int, QOpenGLFramebufferObject] = {}
        self.program: QOpenGLShaderProgram | None = None
        self.test_program: QOpenGLShaderProgram | None = None
        self._resources: dict[int, tuple[QOpenGLContext, ContextResources]] = {}   # keyed by id(context wrapper)
        self.context: QOpenGLContext | None = None
        self.surface: QOffscreenSurface | None = None
        self.frame_count = 0
        self._mask_textures: dict[int, tuple[tuple, QOpenGLTexture]] = {}   # surface id -> (cache key, texture)
        self.fx_renderers: dict[int, FxRenderer] = {}                          # surface id -> FX
        self.project_dir: str | None = None                                    # for project-local FX folders

    # ---- context ----
    def create_context(self) -> None:
        share = QOpenGLContext.globalShareContext()
        self.context = QOpenGLContext()
        if share is not None:
            self.context.setShareContext(share)
            self.context.setFormat(share.format())
        else:
            self.context.setFormat(QSurfaceFormat.defaultFormat())
        if not self.context.create():
            raise RuntimeError("could not create the engine OpenGL context")
        self.surface = QOffscreenSurface()
        self.surface.setFormat(self.context.format())
        self.surface.create()

    def make_current(self) -> bool:
        if self.context is None:
            self.create_context()
        assert self.context is not None and self.surface is not None
        return self.context.makeCurrent(self.surface)

    def done_current(self) -> None:
        if self.context is not None:
            self.context.doneCurrent()

    def ensure_programs(self) -> None:
        if self.program is None:
            self.program = build_program(SURFACE_VERTEX, SURFACE_FRAGMENT)
            self.test_program = build_program(SURFACE_VERTEX, TEST_PATTERN_FRAGMENT)

    def resources(self) -> ContextResources:
        self.ensure_programs()
        ctx = QOpenGLContext.currentContext()
        if ctx is None:
            raise RuntimeError("no current OpenGL context")
        key = id(ctx)
        entry = self._resources.get(key)
        if entry is None:
            assert self.program is not None and self.test_program is not None
            res = ContextResources(self.program, self.test_program)
            # Keeping `ctx` in the entry pins the wrapper so the id stays unique while the context
            # lives; QOpenGLWidget emits aboutToBeDestroyed with the context current, so the VAOs
            # can be destroyed there.
            self._resources[key] = (ctx, res)
            ctx.aboutToBeDestroyed.connect(lambda k=key: self._release_resources(k))
            return res
        return entry[1]

    def _release_resources(self, key: int) -> None:
        # Only the Python references are dropped: the dying context frees its own VAOs/VBOs, and
        # issuing GL calls from `aboutToBeDestroyed` during application teardown crashed
        # (STATUS_STACK_BUFFER_OVERRUN at exit).
        self._resources.pop(key, None)

    def release_context_resources(self) -> None:
        """Call from a context's cleanup with that context current."""
        ctx = QOpenGLContext.currentContext()
        if ctx is not None:
            self._release_resources(id(ctx))

    # ---- project changes ----
    def set_project(self, project: Project) -> None:
        self.make_current()
        for s in self.sources.values():
            s.destroy()
        for fx in self.fx_renderers.values():
            fx.destroy()
        self.sources = {}
        self.fx_renderers = {}
        self.output_fbos = {}
        self.done_current()
        self.project = project
        self.project_dir = str(Path(project.path).parent) if project.path else None

    def source_for(self, visual: Visual) -> MediaSource:
        """The media source for a visual; after undo/redo the Visual object changes but the
        source is kept (movies keep playing, shaders are not recompiled) when id, kind and
        source path still match."""
        src = self.sources.get(visual.id)
        if src is not None and src.visual is not visual:
            if src.visual.kind == visual.kind and src.visual.source == visual.source:
                src.visual = visual
                src.apply_attributes()
            else:
                src.destroy()
                src = None
        if src is None:
            src = create_source(visual)
            self.sources[visual.id] = src
        return src

    def drop_source(self, visual_id: int) -> None:
        src = self.sources.pop(visual_id, None)
        if src is not None:
            self.make_current()
            src.destroy()
            self.done_current()

    def texture_for_visual(self, visual: Visual | None) -> TextureRef | None:
        if visual is None:
            return None
        src = self.sources.get(visual.id)
        return src.texture() if src else None

    # ---- per frame ----
    def frame(self) -> None:
        """Prepare all media and render loopback outputs. Engine context must be current."""
        self.ensure_programs()
        p = self.project
        live_ids = {v.id for v in p.visuals}
        for vid in list(self.sources):
            if vid not in live_ids:
                self.sources.pop(vid).destroy()
        for v in p.visuals:
            src = self.source_for(v)
            if not isinstance(src, LoopbackSource):
                src.prepare(p.bpm)
        # Loopback outputs: render each referenced output into an FBO.
        wanted = {src.output_id for src in self.sources.values() if isinstance(src, LoopbackSource)}
        for oid in list(self.output_fbos):
            if oid not in wanted:
                del self.output_fbos[oid]
        for oid in wanted:
            out = p.output(oid)
            if out is None:
                self.output_fbos.pop(oid, None)   # output deleted: the loopback goes blank
                continue
            fbo = self.output_fbos.get(oid)
            if fbo is None or (fbo.width(), fbo.height()) != out.pixel_size:
                fbo = make_fbo(*out.pixel_size)
                self.output_fbos[oid] = fbo
            fbo.bind()
            self.draw_stage(ViewRect.for_output(out), out.pixel_size, exclude_loopback_of=oid)
            fbo.release()
        for src in self.sources.values():
            if isinstance(src, LoopbackSource):
                fbo = self.output_fbos.get(src.output_id)
                src.ref = TextureRef(fbo.texture(), fbo.width(), fbo.height()) if fbo else None
        for s in p.surfaces:
            if s.fx_active and s.fx_name:
                fx = self.fx_for(s)
                if fx is not None:
                    fx.tick(p.bpm)
        live = {s.id for s in p.surfaces if s.fx_active and s.fx_name}
        for sid in list(self.fx_renderers):
            if sid not in live:
                self.fx_renderers.pop(sid).destroy()
        gl_funcs().glFlush()
        self.frame_count += 1

    def fx_for(self, s: QuadSurface) -> FxRenderer | None:
        """The FX renderer of a surface (created on demand; recreated when the FX name changes)."""
        fx = self.fx_renderers.get(s.id)
        kind = s.shape.value
        if fx is not None and (fx.folder.name != s.fx_name and str(fx.folder) != s.fx_name):
            fx.destroy()
            fx = None
        if fx is None:
            folder = find_fx_folder(s.fx_name, self.project_dir)
            if folder is None:
                return None
            fx = FxRenderer(folder, kind)
            self.fx_renderers[s.id] = fx
        fx.surface_kind = kind
        s.fx_params = fx.apply_params(s.fx_params)
        return fx

    def fx_error(self, s: QuadSurface) -> str | None:
        fx = self.fx_renderers.get(s.id)
        if fx is None:
            return f"FX folder not found: {s.fx_name}" if (s.fx_active and s.fx_name) else None
        return fx.error

    # ---- drawing ----
    def clear_target(self, viewport: tuple[int, int], color: tuple[float, float, float, float]) -> None:
        f = gl_funcs()
        f.glViewport(0, 0, viewport[0], viewport[1])
        f.glClearColor(*color)
        f.glClear(GL_COLOR_BUFFER_BIT)

    def draw_stage(self, view: ViewRect, viewport: tuple[int, int], *, exclude_loopback_of: int | None = None,
                   only_surface: QuadSurface | None = None, clear: tuple[float, float, float, float] = (0, 0, 0, 1),
                   outputs: Iterable[Output] | None = None, clip_to_outputs: bool = False,
                   placeholders: bool = False) -> None:
        """Draw surfaces of the project for the given stage rectangle into the current framebuffer.

        `placeholders`: draw surfaces without media as grey (editor views); outputs draw nothing."""
        f = gl_funcs()
        res = self.resources()
        f.glViewport(0, 0, viewport[0], viewport[1])
        f.glDisable(GL_DEPTH_TEST)
        f.glDisable(GL_SCISSOR_TEST)
        f.glClearColor(*clear)
        f.glClear(GL_COLOR_BUFFER_BIT)
        mat = view.matrix()
        self._current_view = mat
        outs = list(outputs) if outputs is not None else list(self.project.outputs)
        if clip_to_outputs:
            # draw the test pattern / black background of each output rectangle first
            for o in outs:
                self._draw_output_background(o, mat, res, viewport)
        assert self.program is not None
        prog = self.program
        prog.bind()
        prog.setUniformValue("view", _qmatrix3(mat))
        prog.setUniformValue("tex", 0)
        prog.setUniformValue("maskTex", 1)
        surfaces = [only_surface] if only_surface is not None else self.project.surfaces
        for s in surfaces:
            if s is None or not s.visible:
                continue
            visual = self.project.visual(s.visual_id)
            tex = None
            if visual is not None:
                src = self.sources.get(visual.id)
                if isinstance(src, LoopbackSource) and src.output_id == exclude_loopback_of:
                    continue   # an output cannot show itself
                tex = src.texture() if src else None
            self._draw_surface(s, tex, prog, res, placeholders)
        prog.release()
        f.glDisable(GL_BLEND)

    def _draw_output_background(self, o: Output, mat: np.ndarray, res: ContextResources, viewport: tuple[int, int]) -> None:
        if not o.test_pattern:
            return
        assert self.test_program is not None
        tp = self.test_program
        tp.bind()
        tp.setUniformValue("view", _qmatrix3(mat))
        tp.setUniformValue("size", float(o.pixel_size[0]), float(o.pixel_size[1]))
        l, b, r, t = o.rect()
        verts = np.array([
            [l, b, 0, 0, 1, 0, 0], [r, b, 1, 0, 1, 1, 0], [r, t, 1, 1, 1, 1, 1],
            [l, b, 0, 0, 1, 0, 0], [r, t, 1, 1, 1, 1, 1], [l, t, 0, 1, 1, 0, 1],
        ], dtype=np.float32)
        res.test_mesh.upload(verts)
        res.test_mesh.draw()
        tp.release()

    def _draw_surface(self, s: QuadSurface, tex: TextureRef | None, prog: QOpenGLShaderProgram,
                      res: ContextResources, placeholders: bool = False) -> None:
        f = gl_funcs()
        if s.fx_active and s.fx_name and s.shape != Shape.MASK:
            fx = self.fx_for(s)
            if fx is not None and fx.material is not None:
                prog.release()
                try:
                    self._draw_surface_fx(s, tex, fx, res, placeholders)
                finally:
                    prog.bind()
                return
        verts = surface_vertices(s)
        if verts.size == 0:
            return
        res.mesh.upload(verts)
        mask = self._mask_texture(s)
        f.glActiveTexture(GL_TEXTURE0 + 1)
        f.glBindTexture(GL_TEXTURE_2D, mask.textureId() if mask is not None else 0)
        f.glActiveTexture(GL_TEXTURE0)
        f.glBindTexture(GL_TEXTURE_2D, tex.id if tex else 0)
        if s.shape == Shape.MASK:
            prog.setUniformValue("hasTexture", 3)
        else:
            prog.setUniformValue("hasTexture", 1 if tex else (2 if placeholders else 0))
        flip = (1 if s.flip_h else 0) | (2 if s.flip_v else 0) | (4 if (tex and tex.flip_y) else 0)
        prog.setUniformValue("flipMode", int(flip))
        self._composite_uniforms(s, prog, mask is not None)
        _apply_blend(f, s.blend_mode)
        res.mesh.draw()


    def _composite_uniforms(self, s: QuadSurface, prog: QOpenGLShaderProgram, mask_bound: bool) -> None:
        r, g, b = s.color
        prog.setUniformValue("modulation", float(r), float(g), float(b), float(s.opacity))
        se = s.soft_edge
        prog.setUniformValue("softActive", 1 if se.active else 0)
        prog.setUniformValue("softWidth", float(se.left), float(se.right), float(se.top), float(se.bottom))
        prog.setUniformValue("softCurve", float(se.left_curve), float(se.right_curve), float(se.top_curve), float(se.bottom_curve))
        prog.setUniformValue("softGamma", float(se.gamma))
        prog.setUniformValue("blendMode", int(s.blend_mode))
        prog.setUniformValue("hasMask", 1 if mask_bound else 0)
        prog.setUniformValue("shapeMode", 1 if s.shape == Shape.CIRCLE else 0)

    def _draw_surface_fx(self, s: QuadSurface, tex: TextureRef | None, fx: FxRenderer, res: ContextResources,
                         placeholders: bool) -> None:
        f = gl_funcs()
        verts = fx_vertices(s)
        if verts.size == 0:
            return
        mask = self._mask_texture(s)
        f.glActiveTexture(GL_TEXTURE0 + 1)
        f.glBindTexture(GL_TEXTURE_2D, mask.textureId() if mask is not None else 0)
        f.glActiveTexture(GL_TEXTURE0)
        mvp = fx_model_view_projection(s, self._current_view)
        tmat = fx_texture_matrix(s)
        _apply_blend(f, s.blend_mode)
        fx.draw(verts, mvp, tmat, tex.id if tex else 0, (tex.width, tex.height) if tex else (1024, 1024),
                lambda prog: self._composite_uniforms(s, prog, mask is not None),
                self.project.surfaces.index(s) if s in self.project.surfaces else 0, placeholders)

    def _mask_texture(self, s: QuadSurface) -> QOpenGLTexture | None:
        """A grayscale texture of the surface's layer mask (rasterised with QPainter, feathered with
        a box blur), cached per surface until the mask changes."""
        if len(s.mask_points) < 3:
            entry = self._mask_textures.pop(s.id, None)
            if entry is not None:
                entry[1].destroy()
            return None
        key = (tuple(s.mask_points), s.mask_inverted, round(s.mask_feather, 4))
        entry = self._mask_textures.get(s.id)
        if entry is not None and entry[0] == key:
            return entry[1]
        if entry is not None:
            entry[1].destroy()
        tex = texture_from_qimage(rasterise_mask(s.mask_points, s.mask_inverted, s.mask_feather))
        self._mask_textures[s.id] = (key, tex)
        return tex


MASK_RESOLUTION = 512


def rasterise_mask(points: list[tuple[float, float]], inverted: bool, feather: float) -> QImage:
    """Polygon in surface-local coordinates (0..1, y up) -> grayscale image (row 0 = top)."""
    n = MASK_RESOLUTION
    img = QImage(n, n, QImage.Format.Format_Grayscale8)
    img.fill(255 if inverted else 0)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor(0, 0, 0, 0))
    p.setBrush(QColor(0, 0, 0) if inverted else QColor(255, 255, 255))
    p.drawPolygon(QPolygonF([QPointF(x * n, (1.0 - y) * n) for x, y in points]))
    p.end()
    radius = int(round(feather * n))
    if radius > 0:
        ptr = img.constBits()
        ptr.setsize(img.sizeInBytes())
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape(n, img.bytesPerLine())[:, :n].astype(np.float32)
        arr = _box_blur(_box_blur(arr, radius), radius)   # two passes approximate a smooth feather
        out = QImage(n, n, QImage.Format.Format_Grayscale8)
        optr = out.bits()
        optr.setsize(out.sizeInBytes())
        dst = np.frombuffer(optr, dtype=np.uint8).reshape(n, out.bytesPerLine())
        dst[:, :n] = np.clip(arr, 0, 255).astype(np.uint8)
        img = out
    return img.convertToFormat(QImage.Format.Format_RGBA8888)


def _box_blur(a: np.ndarray, r: int) -> np.ndarray:
    if r <= 0:
        return a
    k = 2 * r + 1
    pad = np.pad(a, ((r, r), (r, r)), mode="edge")
    c = np.cumsum(np.cumsum(pad, axis=0), axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    h, w = a.shape
    s = c[k:k + h, k:k + w] - c[:h, k:k + w] - c[k:k + h, :w] + c[:h, :w]
    return s / float(k * k)


def fx_vertices(s: QuadSurface) -> np.ndarray:
    """Vertices for an FX program: [vx, vy, 0, alpha, lx, ly, sx, sy] with vx, vy in -1..1.

    Warp grids are expressed in the surface's own -1..1 space through the inverse homography of its
    corner quad, so `mm_ModelViewProjectionMatrix` reproduces the warped node positions exactly."""
    if s.shape == Shape.TRIANGLE:
        local = [(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)]
        return np.array([[lx * 2 - 1, ly * 2 - 1, 0.0, 1.0, lx, ly, lx, ly] for lx, ly in local], dtype=np.float32)
    if s.warp_points and s.warp_cols > 0 and s.warp_rows > 0:
        cols, rows, pts = s.warp_cols, s.warp_rows, s.warp_points
        if s.warp_smooth:
            pts, cols, rows = smooth_grid(pts, cols, rows, 6)
        h_inv = np.linalg.inv(homography_unit_square_to_quad(s.corners))
        stride = cols + 1
        nodes = []
        for j in range(rows + 1):
            for i in range(cols + 1):
                x, y = pts[j * stride + i]
                u, v, w = h_inv @ np.array([x, y, 1.0])
                u, v = (u / w, v / w) if abs(w) > 1e-12 else (i / cols, j / rows)
                lx, ly = i / cols, j / rows
                nodes.append([u * 2 - 1, v * 2 - 1, 0.0, 1.0, lx, ly, lx, ly])
        tris = grid_triangles(cols, rows)
        return np.array([nodes[k] for tri in tris for k in tri], dtype=np.float32)
    n = 16   # a subdivided quad so vertex-displacing FX have something to bend
    nodes = []
    for j in range(n + 1):
        for i in range(n + 1):
            lx, ly = i / n, j / n
            nodes.append([lx * 2 - 1, ly * 2 - 1, 0.0, 1.0, lx, ly, lx, ly])
    tris = grid_triangles(n, n)
    return np.array([nodes[k] for tri in tris for k in tri], dtype=np.float32)


def fx_model_view_projection(s: QuadSurface, view: np.ndarray) -> QMatrix4x4:
    """-1..1 surface space -> clip space, with the corner-pin homography folded in (z is ignored)."""
    if s.shape == Shape.TRIANGLE:
        (x0, y0), (x1, y1), (x2, y2) = s.corners[:3]
        # local (0,0)->c0, (1,0)->c1, (0.5,1)->c2 ; affine A: stage = A * (lx, ly, 1)
        ax, bx = x1 - x0, x2 - (x0 + x1) / 2
        ay, by = y1 - y0, y2 - (y0 + y1) / 2
        h = np.array([[ax, bx, x0 + 0.0 * ax], [ay, by, y0], [0, 0, 1.0]])
        # (0.5,1) -> x0 + 0.5*ax + bx = x0 + (x1-x0)/2 + x2 - (x0+x1)/2 = x2  (ok)
    else:
        h = homography_unit_square_to_quad(s.corners if not s.perspective else s.corners)
        if not s.perspective:
            h = homography_unit_square_to_quad(s.corners)
            h[2, 0] = h[2, 1] = 0.0   # affine corner pin ignores the perspective terms
    scale = np.array([[0.5, 0, 0.5], [0, 0.5, 0.5], [0, 0, 1.0]])   # -1..1 -> 0..1
    m = view @ h @ scale
    q = QMatrix4x4(float(m[0, 0]), float(m[0, 1]), 0.0, float(m[0, 2]),
                   float(m[1, 0]), float(m[1, 1]), 0.0, float(m[1, 2]),
                   0.0, 0.0, 0.0, 0.0,
                   float(m[2, 0]), float(m[2, 1]), 0.0, float(m[2, 2]))
    return q


def fx_texture_matrix(s: QuadSurface) -> QMatrix4x4:
    """Input-rectangle coordinate (0..1) -> media uv, affine through the uv corners (flips applied)."""
    uv = s.uv_corners
    if len(uv) == 3:
        (u0, v0), (u1, v1), (u2, v2) = uv
        ax, ay = u1 - u0, v1 - v0
        bx, by = u2 - (u0 + u1) / 2, v2 - (v0 + v1) / 2
    else:
        (u0, v0), (u1, v1), _, (u3, v3) = uv
        ax, ay = u1 - u0, v1 - v0
        bx, by = u3 - u0, v3 - v0
    m = QMatrix4x4(ax, bx, 0.0, u0,
                   ay, by, 0.0, v0,
                   0.0, 0.0, 1.0, 0.0,
                   0.0, 0.0, 0.0, 1.0)
    if s.flip_h:
        m = QMatrix4x4(-1, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1) * m
    if s.flip_v:
        m = QMatrix4x4(1, 0, 0, 0, 0, -1, 0, 1, 0, 0, 1, 0, 0, 0, 0, 1) * m
    return m


def surface_vertices(s: QuadSurface) -> np.ndarray:
    """Triangle list for a surface: [x, y, uq, vq, q, lx, ly] per vertex."""
    uvs = s.uv_corners
    if s.shape == Shape.MASK:
        pts = s.corners
        tris = triangulate_polygon(pts)
        if not tris:
            return np.zeros((0, 7), dtype=np.float32)
        verts = [[*pts[k], 0.0, 0.0, 1.0, 0.5, 0.5] for tri in tris for k in tri]
        return np.array(verts, dtype=np.float32)
    if s.shape == Shape.TRIANGLE:
        if len(s.corners) < 3:
            return np.zeros((0, 7), dtype=np.float32)
        tuv = (list(uvs) + [(0.0, 1.0)])[:3]
        local = [(0, 0), (1, 0), (0.5, 1)]
        return np.array([[*s.corners[i], tuv[i][0], tuv[i][1], 1.0, *local[i]] for i in range(3)], dtype=np.float32)
    if s.warp_points and s.warp_cols > 0 and s.warp_rows > 0:
        cols, rows = s.warp_cols, s.warp_rows
        pts = s.warp_points
        if s.warp_smooth:
            pts, cols, rows = smooth_grid(pts, cols, rows, 6)
        # uv per grid node: bilinear in the uv quad
        def uv_at(i: int, j: int) -> tuple[float, float]:
            u, v = i / cols, j / rows
            (u0, v0), (u1, v1), (u2, v2), (u3, v3) = uvs
            x = (1 - u) * (1 - v) * u0 + u * (1 - v) * u1 + u * v * u2 + (1 - u) * v * u3
            y = (1 - u) * (1 - v) * v0 + u * (1 - v) * v1 + u * v * v2 + (1 - u) * v * v3
            return x, y
        nodes = []
        stride = cols + 1
        for j in range(rows + 1):
            for i in range(cols + 1):
                x, y = pts[j * stride + i]
                tu, tv = uv_at(i, j)
                nodes.append([x, y, tu, tv, 1.0, i / cols, j / rows])
        tris = grid_triangles(cols, rows)
        return np.array([nodes[k] for tri in tris for k in tri], dtype=np.float32)
    corners = s.corners
    tcs = projective_texcoords(corners, uvs) if s.perspective else affine_texcoords(uvs)
    local = [(0, 0), (1, 0), (1, 1), (0, 1)]
    v = [[*corners[i], *tcs[i], *local[i]] for i in range(4)]
    return np.array([v[0], v[1], v[2], v[0], v[2], v[3]], dtype=np.float32)


def _apply_blend(f, mode: BlendMode) -> None:
    f.glEnable(GL_BLEND)
    f.glBlendEquation(GL_FUNC_ADD)
    if mode == BlendMode.ADD:
        f.glBlendFunc(GL_ONE, GL_ONE)
    elif mode == BlendMode.SUBTRACT:
        f.glBlendEquation(GL_FUNC_REVERSE_SUBTRACT)
        f.glBlendFunc(GL_ONE, GL_ONE)
    elif mode == BlendMode.MULTIPLY:
        f.glBlendFunc(GL_DST_COLOR, GL_ZERO)
    elif mode == BlendMode.OVER_PREMULTIPLIED:
        f.glBlendFuncSeparate(GL_ONE, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
    elif mode == BlendMode.IGNORE_ALPHA:
        f.glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ZERO)
    else:  # OVER, and the stencil/silhouette modes which are approximated as OVER
        f.glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA)


def _qmatrix3(m: np.ndarray):
    from PyQt6.QtGui import QMatrix3x3
    q = QMatrix3x3()
    for r in range(3):
        for c in range(3):
            q[r, c] = float(m[r, c])
    return q
