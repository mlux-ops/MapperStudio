"""Surface FX renderer: draws a surface through its FX vertex/fragment program.

Vertex layout (fixed attribute locations shared by every FX program, see `FX_VERTEX_LAYOUT`):
    mm_Vertex   = (x, y, 0, alpha)   x, y in -1..1 across the surface
    mm_TexCoord0 = (lx, ly, sx, sy)  input-rectangle coordinate and surface coordinate, both 0..1
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
from PyQt6.QtGui import QMatrix4x4, QOpenGLContext
from PyQt6.QtOpenGL import QOpenGLShaderProgram

from ..isf import IsfError
from ..isf.fx import FxMaterial, load_fx
from ..model.mad_import import MADMAPPER_LIBRARY_CANDIDATES
from .gl import DynamicMesh, ShaderError, build_program, gl_funcs, GL_TRIANGLES
from .materials import IsfUniforms, relocate_error

FX_VERTEX_LAYOUT = [("mm_Vertex", 4, 0), ("mm_TexCoord0", 4, 1)]


def find_fx_folder(name: str, project_dir: str | Path | None = None) -> Path | None:
    """Resolve an FX name: project `FX/Surface2DFX/<name>`, then the MadMapper factory library."""
    candidates = []
    if project_dir:
        candidates.append(Path(project_dir) / "FX" / "Surface2DFX" / name)
    for base in MADMAPPER_LIBRARY_CANDIDATES:
        candidates.append(base / "FactorySurface2DFX" / name)
    p = Path(name)
    if p.is_dir():
        candidates.insert(0, p)
    for c in candidates:
        if c.is_dir() and any(c.glob("*.fs")):
            return c
    return None


def library_fx_names() -> list[str]:
    for base in MADMAPPER_LIBRARY_CANDIDATES:
        d = base / "FactorySurface2DFX"
        if d.is_dir():
            return sorted(p.name for p in d.iterdir() if p.is_dir() and any(p.glob("*.vs")))
    return []


def build_fx_program(vertex: str, fragment: str) -> QOpenGLShaderProgram:
    from PyQt6.QtOpenGL import QOpenGLShader
    prog = QOpenGLShaderProgram()
    if not prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, vertex):
        raise ShaderError("vertex shader: " + prog.log())
    if not prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, fragment):
        raise ShaderError("fragment shader: " + prog.log())
    for name, _n, loc in FX_VERTEX_LAYOUT:
        prog.bindAttributeLocation(name, loc)
    if not prog.link():
        raise ShaderError("link: " + prog.log())
    return prog


class FxRenderer:
    """One per surface with an active FX; programs are shared across contexts, meshes are per context."""

    def __init__(self, folder: Path, surface_kind: str):
        self.folder = folder
        self.material: FxMaterial | None = None
        self.program: QOpenGLShaderProgram | None = None
        self.uniforms: IsfUniforms | None = None
        self.error: str | None = None
        self.surface_kind = surface_kind
        self._meshes: dict[int, tuple[QOpenGLContext, DynamicMesh]] = {}
        self._frame = 0
        self._last_time = time.perf_counter()
        try:
            self.material = load_fx(folder)
            self.material.surface_kind = surface_kind
        except (IsfError, OSError) as exc:
            self.error = str(exc)

    # ---- parameters ----
    def apply_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Push surface parameter values into the FX; label-keyed imports are converted to names."""
        if self.material is None:
            return params
        by_label = bool(params.get("__by_label__"))
        self.material.apply_values(params, by_label=by_label)
        if by_label:
            return {i.name: self.material.values[i.name] for i in self.material.inputs}
        return params

    def tick(self, bpm: float) -> None:
        if self.material is not None:
            self.material.tick(bpm)

    # ---- GL ----
    def ensure_program(self) -> bool:
        if self.material is None:
            return False
        if self.material.surface_kind != self.surface_kind:
            self.material.surface_kind = self.surface_kind
        if self.program is not None and not self.material.needs_rebuild():
            return True
        try:
            src = self.material.assemble()
            program = build_fx_program(src.vertex, src.fragment)
        except (ShaderError, IsfError) as exc:
            self.error = relocate_error(str(exc), self.material)
            return self.program is not None
        self.program = program
        self.uniforms = IsfUniforms(program)
        self.error = None
        return True

    def mesh(self) -> DynamicMesh:
        ctx = QOpenGLContext.currentContext()
        key = id(ctx)
        entry = self._meshes.get(key)
        if entry is None:
            assert self.program is not None
            m = DynamicMesh(self.program, [(n, c) for n, c, _ in FX_VERTEX_LAYOUT], locations=[l for _, _, l in FX_VERTEX_LAYOUT])
            self._meshes[key] = (ctx, m)
            ctx.aboutToBeDestroyed.connect(lambda k=key: self._meshes.pop(k, None))
            return m
        return entry[1]

    def instance_count(self) -> int:
        if self.material is None:
            return 1
        spec = self.material.instance_count_spec
        if spec is None:
            return 1
        if isinstance(spec, (int, float)) and not isinstance(spec, bool):
            return max(1, int(spec))
        if isinstance(spec, str):
            v = self.material.generator_values().get(spec)
            if v is None:
                v = self.material.values.get(spec, 1)
            try:
                return max(1, min(int(v), 1_000_000))
            except (TypeError, ValueError):
                return 1
        return 1

    def draw(self, vertices: np.ndarray, mvp: QMatrix4x4, texture_matrix: QMatrix4x4, input_tex_id: int,
             input_size: tuple[int, int], set_composite_uniforms, surface_index: int, preview: bool) -> None:
        """Draw with the current context. `set_composite_uniforms(program)` sets the shared compositing
        uniforms (modulation, soft edge, mask, shape, blend)."""
        if not self.ensure_program() or self.program is None or self.uniforms is None or self.material is None:
            return
        now = time.perf_counter()
        dt = now - self._last_time
        self._last_time = now
        self._frame += 1
        f = gl_funcs()
        p = self.program
        p.bind()
        u = self.uniforms
        src = self.material.program
        assert src is not None
        u.upload(self.material, src, input_size[0], input_size[1], dt, self._frame)
        loc = u.loc("mm_ModelViewProjectionMatrix")
        if loc >= 0:
            p.setUniformValue(loc, mvp)
        loc = u.loc("mm_TextureMatrix")
        if loc >= 0:
            p.setUniformValue(loc, texture_matrix)
        u.seti("mm_IsRenderingPreview", 1 if preview else 0)
        u.seti("mm_SurfaceIndex", surface_index)
        u.seti("inputImage", 0)
        u.set2("inputImage_size", float(input_size[0]), float(input_size[1]))
        u.seti("maskTex", 1)
        set_composite_uniforms(p)
        f.glActiveTexture(0x84C0)
        f.glBindTexture(0x0DE1, input_tex_id)
        mesh = self.mesh()
        mesh.upload(vertices)
        n = self.instance_count()
        mesh.vao.bind()
        if n > 1:
            f.glDrawArraysInstanced(GL_TRIANGLES, 0, mesh.count, n)
        else:
            f.glDrawArrays(GL_TRIANGLES, 0, mesh.count)
        mesh.vao.release()
        p.release()

    def destroy(self) -> None:
        for _ctx, m in self._meshes.values():
            m.destroy()
        self._meshes = {}
        self.program = None
        self.uniforms = None
