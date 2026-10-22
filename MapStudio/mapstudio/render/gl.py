"""Small helpers over Qt's OpenGL classes (core profile 3.3).

Everything here must be called with a GL context current.  Textures, programs and buffers are
shared between all MapStudio contexts (the application sets AA_ShareOpenGLContexts); vertex
array objects and framebuffer objects are *not* shareable and must be created per context.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass

import numpy as np
from PyQt6.QtGui import QImage, QOpenGLContext, QSurfaceFormat
from PyQt6.QtOpenGL import (
    QOpenGLBuffer, QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat, QOpenGLFunctions_4_1_Core,
    QOpenGLShader, QOpenGLShaderProgram, QOpenGLTexture, QOpenGLVersionFunctionsFactory, QOpenGLVersionProfile,
    QOpenGLVertexArrayObject,
)

GL_TEXTURE0 = 0x84C0
GL_TEXTURE_2D = 0x0DE1
GL_RGBA = 0x1908
GL_RGBA8 = 0x8058
GL_UNSIGNED_BYTE = 0x1401
GL_FLOAT = 0x1406
GL_TRIANGLES = 0x0004
GL_TRIANGLE_STRIP = 0x0005
GL_BLEND = 0x0BE2
GL_DEPTH_TEST = 0x0B71
GL_SCISSOR_TEST = 0x0C11
GL_COLOR_BUFFER_BIT = 0x00004000
GL_ONE = 1
GL_ZERO = 0
GL_SRC_ALPHA = 0x0302
GL_ONE_MINUS_SRC_ALPHA = 0x0303
GL_DST_COLOR = 0x0306
GL_ONE_MINUS_SRC_COLOR = 0x0301
GL_FUNC_ADD = 0x8006
GL_FUNC_REVERSE_SUBTRACT = 0x800B
GL_LINEAR = 0x2601
GL_CLAMP_TO_EDGE = 0x812F
GL_REPEAT = 0x2901
GL_MIRRORED_REPEAT = 0x8370
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_MAG_FILTER = 0x2800
GL_TEXTURE_WRAP_S = 0x2802
GL_TEXTURE_WRAP_T = 0x2803
GL_UNPACK_ALIGNMENT = 0x0CF5


class ShaderError(RuntimeError):
    pass


# Keyed by the wrapper id; the entry keeps the QOpenGLContext wrapper alive so the id stays stable,
# and `aboutToBeDestroyed` removes the entry before another context can reuse the address.
_FUNCS: dict[int, tuple[QOpenGLContext, "QOpenGLFunctions_4_1_Core"]] = {}


def gl_funcs() -> "QOpenGLFunctions_4_1_Core":
    """The OpenGL 4.1 core function table for the current context (cached per context)."""
    ctx = QOpenGLContext.currentContext()
    if ctx is None:
        raise RuntimeError("no current OpenGL context")
    key = id(ctx)
    entry = _FUNCS.get(key)
    f = entry[1] if entry is not None else None
    if f is None:
        profile = QOpenGLVersionProfile()
        profile.setVersion(4, 1)
        profile.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        f = QOpenGLVersionFunctionsFactory.get(profile, ctx)
        if f is None or not f.initializeOpenGLFunctions():
            raise RuntimeError("OpenGL 4.1 core functions are not available in this context "
                               f"(context format {ctx.format().majorVersion()}.{ctx.format().minorVersion()})")
        _FUNCS[key] = (ctx, f)
        ctx.aboutToBeDestroyed.connect(lambda k=key: _FUNCS.pop(k, None))
    return f


def forget_context_funcs() -> None:
    ctx = QOpenGLContext.currentContext()
    if ctx is not None:
        _FUNCS.pop(id(ctx), None)


def build_program(vertex: str, fragment: str) -> QOpenGLShaderProgram:
    prog = QOpenGLShaderProgram()
    if not prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, vertex):
        raise ShaderError("vertex shader: " + prog.log())
    if not prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, fragment):
        raise ShaderError("fragment shader: " + prog.log())
    if not prog.link():
        raise ShaderError("link: " + prog.log())
    return prog


class FullscreenQuad:
    """A VAO/VBO drawing a full-screen quad with `mad_Position` (vec4) and `mad_TexCoord0` (vec4)."""

    def __init__(self, program: QOpenGLShaderProgram):
        self.vao = QOpenGLVertexArrayObject()
        self.vao.create()
        self.vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self.vbo.create()
        data = np.array([
            # x, y, z, w,   u, v, 0, 1
            -1, -1, 0, 1, 0, 0, 0, 1,
            1, -1, 0, 1, 1, 0, 0, 1,
            -1, 1, 0, 1, 0, 1, 0, 1,
            1, 1, 0, 1, 1, 1, 0, 1,
        ], dtype=np.float32)
        self.vao.bind()
        self.vbo.bind()
        self.vbo.allocate(data.tobytes(), data.nbytes)
        loc_pos = program.attributeLocation("mad_Position")
        loc_uv = program.attributeLocation("mad_TexCoord0")
        if loc_pos >= 0:
            program.enableAttributeArray(loc_pos)
            program.setAttributeBuffer(loc_pos, GL_FLOAT, 0, 4, 32)
        if loc_uv >= 0:
            program.enableAttributeArray(loc_uv)
            program.setAttributeBuffer(loc_uv, GL_FLOAT, 16, 4, 32)
        self.vao.release()
        self.vbo.release()

    def draw(self) -> None:
        self.vao.bind()
        gl_funcs().glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
        self.vao.release()

    def destroy(self) -> None:
        self.vbo.destroy()
        self.vao.destroy()


class DynamicMesh:
    """A VAO/VBO for an arbitrary triangle list with interleaved float attributes."""

    def __init__(self, program: QOpenGLShaderProgram, layout: list[tuple[str, int]],
                 locations: list[int] | None = None):
        """`layout`: [(attribute name, component count), ...] in buffer order; `locations` overrides
        the attribute locations looked up on `program` (for programs linked with bound locations)."""
        self.vao = QOpenGLVertexArrayObject()
        self.vao.create()
        self.vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self.vbo.create()
        self.vbo.setUsagePattern(QOpenGLBuffer.UsagePattern.DynamicDraw)
        self.stride = sum(n for _, n in layout) * 4
        self.vao.bind()
        self.vbo.bind()
        self.vbo.allocate(self.stride * 6)
        offset = 0
        for k, (name, n) in enumerate(layout):
            loc = locations[k] if locations is not None else program.attributeLocation(name)
            if loc >= 0:
                program.enableAttributeArray(loc)
                program.setAttributeBuffer(loc, GL_FLOAT, offset, n, self.stride)
            offset += n * 4
        self.vao.release()
        self.vbo.release()
        self.count = 0

    def upload(self, vertices: np.ndarray) -> None:
        data = np.ascontiguousarray(vertices, dtype=np.float32)
        self.vbo.bind()
        if data.nbytes > self.vbo.size():
            self.vbo.allocate(data.tobytes(), data.nbytes)
        else:
            self.vbo.write(0, data.tobytes(), data.nbytes)
        self.vbo.release()
        self.count = data.nbytes // self.stride

    def draw(self) -> None:
        if self.count == 0:
            return
        self.vao.bind()
        gl_funcs().glDrawArrays(GL_TRIANGLES, 0, self.count)
        self.vao.release()

    def destroy(self) -> None:
        self.vbo.destroy()
        self.vao.destroy()


def make_fbo(width: int, height: int) -> QOpenGLFramebufferObject:
    fmt = QOpenGLFramebufferObjectFormat()
    fmt.setInternalTextureFormat(GL_RGBA8)
    fmt.setTextureTarget(GL_TEXTURE_2D)
    fbo = QOpenGLFramebufferObject(max(1, width), max(1, height), fmt)
    tex = fbo.texture()
    f = gl_funcs()
    f.glBindTexture(GL_TEXTURE_2D, tex)
    f.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    f.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    f.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
    f.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
    f.glBindTexture(GL_TEXTURE_2D, 0)
    return fbo


def texture_from_qimage(image: QImage, *, mipmaps: bool = False) -> QOpenGLTexture:
    img = image.convertToFormat(QImage.Format.Format_RGBA8888)
    tex = QOpenGLTexture(img.mirrored(False, True), QOpenGLTexture.MipMapGeneration.GenerateMipMaps if mipmaps
                         else QOpenGLTexture.MipMapGeneration.DontGenerateMipMaps)
    tex.setMinificationFilter(QOpenGLTexture.Filter.LinearMipMapLinear if mipmaps else QOpenGLTexture.Filter.Linear)
    tex.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
    tex.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
    return tex


class StreamingTexture:
    """A 2D RGBA texture updated every frame from QImage data of a fixed size."""

    def __init__(self) -> None:
        self.texture: QOpenGLTexture | None = None
        self.width = 0
        self.height = 0

    def update(self, image: QImage) -> None:
        img = image.convertToFormat(QImage.Format.Format_RGBA8888).mirrored(False, True)
        if self.texture is None or img.width() != self.width or img.height() != self.height:
            if self.texture is not None:
                self.texture.destroy()
            self.texture = QOpenGLTexture(QOpenGLTexture.Target.Target2D)
            self.texture.setFormat(QOpenGLTexture.TextureFormat.RGBA8_UNorm)
            self.texture.setSize(img.width(), img.height())
            self.texture.setMipLevels(1)
            self.texture.allocateStorage()
            self.texture.setMinificationFilter(QOpenGLTexture.Filter.Linear)
            self.texture.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
            self.texture.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
            self.width, self.height = img.width(), img.height()
        ptr = img.constBits()
        ptr.setsize(img.sizeInBytes())
        f = gl_funcs()
        f.glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        self.texture.bind()
        f.glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, self.width, self.height, GL_RGBA, GL_UNSIGNED_BYTE, ptr)
        self.texture.release()

    @property
    def texture_id(self) -> int:
        return self.texture.textureId() if self.texture is not None else 0

    def destroy(self) -> None:
        if self.texture is not None:
            self.texture.destroy()
            self.texture = None


@dataclass
class TextureRef:
    """What a surface samples: a GL texture name and its size in pixels."""
    id: int
    width: int
    height: int
    flip_y: bool = False   # True when the image is stored top-down (FBO textures are bottom-up)
