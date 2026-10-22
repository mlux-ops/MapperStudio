"""Assemble GLSL programs from an ISF document.

The layout reproduces what MadMapper generates (see `03-materials-isf.md`, "Shader assembly"):
version line, entry-point defines, globals, the IMG_* macros, one uniform per INPUT with its
default, one `uniform float` per GENERATOR, imported textures, the stage-specific built-ins and
finally the user source and a `main()` wrapper around `materialColorForPixel`.

Only the parts that matter for a single-pass fragment material are implemented; the vertex
stage is the fixed full-screen quad.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .header import IsfDocument, IsfError
from .inputs import InputType, IsfInput

INCLUDE_DIR = Path(__file__).resolve().parent / "glsl"
_INCLUDE_RE = re.compile(r'^[ \t]*#include[ \t]+"([^"]+)"[ \t]*$', re.MULTILINE)
_INCOMPLETE_INCLUDE_RE = re.compile(r"^[ \t]*#include\b.*$", re.MULTILINE)

DEFAULT_GLSL_VERSION = "150 core"

MACROS = """// Macros
#define IMG_SIZE(s) s##_size
#define IMG_NORM_PIXEL(s, location) texture(s,(location)*s##_mult+s##_add)
#define IMG_PIXEL(s, location) IMG_NORM_PIXEL(s, vec2(0,1) + vec2(1,-1) * (location) / RENDERSIZE)
#define IMG_THIS_NORM_PIXEL(s) IMG_NORM_PIXEL(s, isf_FragNormCoord)
#define IMG_THIS_PIXEL(s) IMG_PIXEL(s,gl_FragCoord.xy)
#define IMG_NORM_PIXEL_LOD(s, location, lod) textureLod(s,(location)*s##_mult+s##_add,lod)
#define IMG_TEXEL_FETCH(s, location, lod) texelFetch(s, ivec2(location), lod)
"""

VERTEX_SOURCE_TEMPLATE = """#version {version}
in vec4 mad_Position;
in vec4 mad_TexCoord0;
out vec2 isf_FragNormCoord;
void main() {{
    gl_Position = mad_Position;
    isf_FragNormCoord = mad_TexCoord0.xy;
}}
"""


@dataclass
class AssembledProgram:
    vertex: str
    fragment: str
    uniform_inputs: list[IsfInput]       # inputs that became uniforms (in declaration order)
    generator_names: list[str]
    texture_inputs: list[IsfInput]       # sampler inputs (texture unit = index + 1; unit 0 = mm_LastFrame)
    imported_names: list[str]
    body_line_offset: int                # line number in the assembled fragment where the user body starts
    uses_time: bool
    uses_mouse: bool


def _fmt(v: float) -> str:
    s = repr(float(v))
    if "e" in s or "E" in s:
        s = f"{float(v):.9f}"
    if "." not in s:
        s += ".0"
    return s


def _default_literal(inp: IsfInput) -> str:
    t = inp.type
    if t == InputType.FLOAT:
        return _fmt(inp.default)
    if t in (InputType.INT, InputType.LONG):
        return str(int(inp.default))
    if t in (InputType.BOOL, InputType.EVENT):
        return "true" if inp.default else "false"
    if t == InputType.COLOR:
        return "vec4(" + ",".join(_fmt(x) for x in inp.default) + ")"
    if t in (InputType.POINT2D, InputType.FLOAT_RANGE):
        return "vec2(" + ",".join(_fmt(x) for x in inp.default) + ")"
    if t == InputType.POINT3D:
        return "vec3(" + ",".join(_fmt(x) for x in inp.default) + ")"
    if t == InputType.POINT4D:
        return "vec4(" + ",".join(_fmt(x) for x in inp.default) + ")"
    return ""


def resolve_includes(source: str, search_dirs: list[Path], _depth: int = 0) -> str:
    """Expand `#include "file"` lines; built-in libraries live in `isf/glsl/`."""
    if _depth > 8:
        raise IsfError("#include nesting too deep")
    for m in _INCOMPLETE_INCLUDE_RE.finditer(source):
        if not _INCLUDE_RE.match(m.group(0)):
            raise IsfError(f"Incomplete \"#include\" directive: {m.group(0).strip()}")

    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        for d in [*search_dirs, INCLUDE_DIR]:
            cand = d / name
            if cand.is_file():
                text = cand.read_text(encoding="utf-8", errors="replace")
                return f"// ---- begin {name}\n" + resolve_includes(text, [cand.parent, *search_dirs], _depth + 1) + f"\n// ---- end {name}\n"
        raise IsfError(f"Included file not found: {name}")

    return _INCLUDE_RE.sub(repl, source)


_LEGACY = [
    (re.compile(r"\bvv_vertShaderInit\b"), "isf_vertShaderInit"),
    (re.compile(r"\bvv_FragNormCoord\b"), "isf_FragNormCoord"),
    (re.compile(r"\btexture2D\b"), "texture"),
    (re.compile(r"\btextureCube\b"), "texture"),
    (re.compile(r"\btextureRect\b"), "texture"),
    (re.compile(r"\bgl_FragColor\b"), "FragColor"),
]


def _legacy_rewrites(body: str) -> str:
    for rx, rep in _LEGACY:
        body = rx.sub(rep, body)
    body = re.sub(r"^(\s*)varying\s+", r"\1in ", body, flags=re.MULTILINE)
    return body


def assemble_material(doc: IsfDocument, body: str, *, entry: str = "materialColorForPixel",
                      defines: dict[str, int] | None = None, search_dirs: list[Path] | None = None,
                      glsl_version: str | None = None, requires_last_frame: bool = False) -> AssembledProgram:
    """Build vertex + fragment sources for a material whose body defines `entry`."""
    version = glsl_version or doc.glsl_version or DEFAULT_GLSL_VERSION
    body = resolve_includes(_legacy_rewrites(body), search_dirs or [])
    all_text = body
    uses_time = bool(re.search(r"\bTIME\b|\bCLOCK_TIME\b|\bTIMEDELTA\b", all_text))
    uses_mouse = bool(re.search(r"\bMOUSEPOS\b|\bMOUSEKEYSTATE\b", all_text))

    lines: list[str] = [f"#version {version}", f"#define {entry.upper()}_ENTRY 1"]
    # generate_as_define flags: NAME_IS_<Value> for the selected option
    defines = defines or {}
    for inp in doc.inputs:
        if inp.type == InputType.LONG and "generate_as_define" in inp.flags:
            idx = defines.get(inp.name, int(inp.default))
            if 0 <= idx < len(inp.values):
                val = str(inp.values[idx])
                ident = re.sub(r"[^A-Za-z0-9_]", "_", val)
                lines.append(f"#define {inp.name}_IS_{ident} 1")
    lines.append("")
    lines.append("// Globals")
    if uses_time:
        lines += ["uniform float TIME;", "uniform float CLOCK_TIME;", "uniform vec4 DATE;",
                  "uniform float TIMEDELTA;", "uniform float FRAMEINDEX;"]
    lines += ["uniform int PASSINDEX=0;", "uniform vec2 RENDERSIZE;"]
    if uses_mouse:
        lines += ["uniform int MOUSEKEYSTATE;", "uniform vec2 MOUSEPOS;"]
    lines.append("")
    lines.append(MACROS)

    lines.append("// Inputs")
    uniform_inputs: list[IsfInput] = []
    texture_inputs: list[IsfInput] = []
    for inp in doc.inputs:
        gt = inp.glsl_type
        if not gt:
            continue  # strings, curves, vectors: not uniforms in this implementation
        if inp.is_sampler:
            size_t = "vec3" if inp.type == InputType.IMAGE_3D else "vec2"
            size_v = "vec3(32,32,32)" if inp.type == InputType.IMAGE_3D else "vec2(1920,1080)"
            lines += [f"uniform {gt} {inp.name};", f"uniform {size_t} {inp.name}_size={size_v};",
                      f"uniform ivec2 {inp.name}_mult=ivec2(1,1);", f"uniform vec2 {inp.name}_add=vec2(0,0);"]
            texture_inputs.append(inp)
            continue
        lit = _default_literal(inp)
        lines.append(f"uniform {gt} {inp.name}" + (f" = {lit};" if lit else ";"))
        uniform_inputs.append(inp)
    lines.append("")

    lines.append("// Generated Attributes")
    gen_names = [g["NAME"] for g in doc.generators]
    for g in gen_names:
        lines.append(f"uniform float {g} = 0.0;")
    lines.append("")

    lines.append("// Imported Textures")
    imported_names = [t.name for t in doc.imported]
    for t in doc.imported:
        sampler = {"cube": "samplerCube", "3D": "sampler3D"}.get(t.kind, "sampler2D")
        lines += [f"uniform {sampler} {t.name};", f"uniform vec2 {t.name}_size=vec2(1,1);",
                  f"const ivec2 {t.name}_mult=ivec2(1,1);", f"const vec2 {t.name}_add=vec2(0,0);"]
    if requires_last_frame:
        lines += ["uniform sampler2D mm_LastFrame;", "uniform vec2 mm_LastFrame_size=vec2(1,1);",
                  "const ivec2 mm_LastFrame_mult=ivec2(1,1);", "const vec2 mm_LastFrame_add=vec2(0,0);"]
    lines.append("")
    lines += ["in vec2 isf_FragNormCoord;", "out vec4 FragColor;", ""]
    body_line_offset = len(lines) + 1
    lines.append(f"#line 1")
    lines.append(body)
    lines.append("")
    lines.append("void main() {")
    lines.append(f"    FragColor = {entry}(isf_FragNormCoord);")
    lines.append("}")
    fragment = "\n".join(lines) + "\n"
    vertex = VERTEX_SOURCE_TEMPLATE.format(version=version)
    return AssembledProgram(vertex, fragment, uniform_inputs, gen_names, texture_inputs, imported_names,
                            body_line_offset, uses_time, uses_mouse)
