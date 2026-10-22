"""Render ISF materials to textures.

`MaterialRenderer` compiles the assembled program, uploads uniform values every frame and draws
a full-screen quad into a framebuffer of the material's render size.  Compile errors keep the
previous good program (hot reload semantics) and are exposed via `error`.

`IsfUniforms` is the uniform-upload logic shared with the Surface FX renderer.
"""
from __future__ import annotations

import datetime
import re
import time
from pathlib import Path
from typing import Any

from PyQt6.QtGui import QImage
from PyQt6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLShaderProgram, QOpenGLTexture

from ..isf import Material, IsfError
from ..isf.assembly import AssembledProgram
from ..isf.inputs import InputType
from .gl import (
    FullscreenQuad, ShaderError, build_program, gl_funcs, make_fbo, texture_from_qimage, GL_TEXTURE0,
    GL_TEXTURE_2D, GL_COLOR_BUFFER_BIT, GL_BLEND, GL_DEPTH_TEST, TextureRef, GL_REPEAT, GL_CLAMP_TO_EDGE,
    GL_MIRRORED_REPEAT,
)

_WRAP = {"REPEAT": GL_REPEAT, "CLAMP_TO_EDGE": GL_CLAMP_TO_EDGE, "MIRRORED_REPEAT": GL_MIRRORED_REPEAT}


class IsfUniforms:
    """Caches uniform locations of a program and uploads ISF values (inputs, generators, globals)."""

    def __init__(self, program: QOpenGLShaderProgram):
        self.program = program
        self._locs: dict[str, int] = {}

    def loc(self, name: str) -> int:
        loc = self._locs.get(name)
        if loc is None:
            loc = self.program.uniformLocation(name)
            self._locs[name] = loc
        return loc

    def setf(self, name: str, value: float) -> None:
        loc = self.loc(name)
        if loc >= 0:
            self.program.setUniformValue(loc, float(value))

    def seti(self, name: str, value: int) -> None:
        loc = self.loc(name)
        if loc >= 0:
            self.program.setUniformValue(loc, int(value))

    def set2(self, name: str, x: float, y: float) -> None:
        loc = self.loc(name)
        if loc >= 0:
            self.program.setUniformValue(loc, float(x), float(y))

    def set4(self, name: str, x: float, y: float, z: float, w: float) -> None:
        loc = self.loc(name)
        if loc >= 0:
            self.program.setUniformValue(loc, float(x), float(y), float(z), float(w))

    def set_input(self, name: str, inp_type: InputType, value: Any) -> None:
        loc = self.loc(name)
        if loc < 0:
            return
        p = self.program
        if inp_type == InputType.FLOAT:
            p.setUniformValue(loc, float(value))
        elif inp_type in (InputType.INT, InputType.LONG):
            p.setUniformValue(loc, int(value))
        elif inp_type in (InputType.BOOL, InputType.EVENT):
            p.setUniformValue(loc, 1 if value else 0)
        elif inp_type in (InputType.COLOR, InputType.POINT4D):
            v = list(value) + [1.0] * (4 - len(value))
            p.setUniformValue(loc, float(v[0]), float(v[1]), float(v[2]), float(v[3]))
        elif inp_type in (InputType.POINT2D, InputType.FLOAT_RANGE):
            p.setUniformValue(loc, float(value[0]), float(value[1]))
        elif inp_type == InputType.POINT3D:
            p.setUniformValue(loc, float(value[0]), float(value[1]), float(value[2]))

    def upload(self, material: Material, prog: AssembledProgram, width: int, height: int, dt: float,
               frame_index: int) -> None:
        """Globals (TIME...), RENDERSIZE, every INPUT uniform and every generator value."""
        if prog.uses_time:
            self.setf("TIME", material.time)
            self.setf("CLOCK_TIME", time.time() % 86400.0)
            self.setf("TIMEDELTA", dt)
            self.setf("FRAMEINDEX", float(frame_index))
            d = datetime.datetime.now()
            self.set4("DATE", float(d.year), float(d.month), float(d.day), float(d.hour * 3600 + d.minute * 60 + d.second))
        self.set2("RENDERSIZE", float(width), float(height))
        for inp in prog.uniform_inputs:
            self.set_input(inp.name, inp.type, material.values.get(inp.name, inp.default))
        for name, val in material.generator_values().items():
            self.setf(name, val)


class MaterialRenderer:
    def __init__(self, material: Material, width: int, height: int):
        self.material = material
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self.program: QOpenGLShaderProgram | None = None
        self.uniforms: IsfUniforms | None = None
        self.quad: FullscreenQuad | None = None
        self.fbo: QOpenGLFramebufferObject | None = None
        self.last_fbo: QOpenGLFramebufferObject | None = None
        self.error: str | None = None
        self.imported: dict[str, QOpenGLTexture] = {}
        self._frame = 0
        self._last_time = time.perf_counter()

    # ---- lifecycle (context must be current) ----
    def ensure_resources(self) -> None:
        if self.fbo is None:
            self.fbo = make_fbo(self.width, self.height)
            if self.material.doc.requires_last_frame:
                self.last_fbo = make_fbo(self.width, self.height)
        if self.program is None or self.material.needs_rebuild():
            self.rebuild()
        if not self.imported:
            self._load_imported()

    def rebuild(self) -> bool:
        try:
            prog_src = self.material.assemble()
            program = build_program(prog_src.vertex, prog_src.fragment)
        except (ShaderError, IsfError) as exc:
            self.error = relocate_error(str(exc), self.material)
            return False
        if self.program is not None:
            self.program.removeAllShaders()
        self.program = program
        self.uniforms = IsfUniforms(program)
        self.error = None
        if self.quad is not None:
            self.quad.destroy()
        self.quad = FullscreenQuad(program)
        return True

    def reload_source(self) -> bool:
        """Re-read the .fs from disk (hot reload); keeps the current parameter values."""
        from ..isf import load_material
        try:
            fresh = load_material(self.material.source.fragment_path)
        except IsfError as exc:
            self.error = str(exc)
            return False
        fresh.apply_values(dict(self.material.values))
        self.material = fresh
        return self.rebuild()   # on failure the previous program stays in use and `error` is set

    def resize(self, width: int, height: int) -> None:
        width, height = max(1, int(width)), max(1, int(height))
        if (width, height) == (self.width, self.height):
            return
        self.width, self.height = width, height
        if self.fbo is not None:
            self.fbo = make_fbo(width, height)
            if self.last_fbo is not None:
                self.last_fbo = make_fbo(width, height)

    def destroy(self) -> None:
        if self.quad is not None:
            self.quad.destroy()
            self.quad = None
        for t in self.imported.values():
            t.destroy()
        self.imported = {}
        self.fbo = None
        self.last_fbo = None
        self.program = None
        self.uniforms = None

    def _load_imported(self) -> None:
        folder = self.material.source.folder
        for t in self.material.doc.imported:
            path = t.path if isinstance(t.path, str) else (t.path[0] if t.path else "")
            if not path:
                continue
            p = Path(path) if Path(path).is_absolute() else folder / path
            img = QImage(str(p))
            if img.isNull():
                self.error = f"imported texture not found: {p.name}"
                continue
            tex = texture_from_qimage(img, mipmaps=True)
            wrap = _WRAP.get(t.wrap.upper(), GL_CLAMP_TO_EDGE)
            tex.setWrapMode(QOpenGLTexture.WrapMode.Repeat if wrap == GL_REPEAT else
                            QOpenGLTexture.WrapMode.MirroredRepeat if wrap == GL_MIRRORED_REPEAT else
                            QOpenGLTexture.WrapMode.ClampToEdge)
            self.imported[t.name] = tex

    # ---- per frame ----
    def render(self, bpm: float, input_textures: dict[str, TextureRef] | None = None) -> bool:
        """Render one frame into the material's FBO. Returns False when there is no usable program."""
        self.ensure_resources()
        if self.program is None or self.fbo is None or self.quad is None or self.uniforms is None:
            return False
        m = self.material
        m.tick(bpm)
        now = time.perf_counter()
        dt = now - self._last_time
        self._last_time = now
        self._frame += 1

        if self.last_fbo is not None:
            self.fbo, self.last_fbo = self.last_fbo, self.fbo   # ping-pong: previous frame is readable

        f = gl_funcs()
        self.fbo.bind()
        f.glViewport(0, 0, self.width, self.height)
        f.glDisable(GL_BLEND)
        f.glDisable(GL_DEPTH_TEST)
        f.glClearColor(0.0, 0.0, 0.0, 0.0)
        f.glClear(GL_COLOR_BUFFER_BIT)
        p = self.program
        p.bind()
        prog = m.program
        assert prog is not None
        u = self.uniforms
        u.upload(m, prog, self.width, self.height, dt, self._frame)

        unit = 0
        if self.last_fbo is not None:
            f.glActiveTexture(GL_TEXTURE0 + unit)
            f.glBindTexture(GL_TEXTURE_2D, self.last_fbo.texture())
            u.seti("mm_LastFrame", unit)
            u.set2("mm_LastFrame_size", float(self.width), float(self.height))
            unit += 1
        for name, tex in self.imported.items():
            f.glActiveTexture(GL_TEXTURE0 + unit)
            tex.bind()
            u.seti(name, unit)
            u.set2(name + "_size", float(tex.width()), float(tex.height()))
            unit += 1
        for inp in prog.texture_inputs:
            ref = (input_textures or {}).get(inp.name)
            f.glActiveTexture(GL_TEXTURE0 + unit)
            f.glBindTexture(GL_TEXTURE_2D, ref.id if ref else 0)
            u.seti(inp.name, unit)
            u.set2(inp.name + "_size", float(ref.width if ref else 1), float(ref.height if ref else 1))
            unit += 1
        self.quad.draw()
        p.release()
        f.glActiveTexture(GL_TEXTURE0)
        self.fbo.release()
        return True

    def texture(self) -> TextureRef | None:
        if self.fbo is None:
            return None
        return TextureRef(self.fbo.texture(), self.width, self.height)


def relocate_error(message: str, material: Material) -> str:
    """Shader error text for the user. The body is emitted after `#line 1`, so compilers already
    report line numbers relative to the material source; this normalises the "0(123)" prefix."""
    if material.program is None:
        return message
    return re.sub(r"(0\(|0:)(\d+)", lambda m: f"{m.group(1)}{int(m.group(2))}", message)
