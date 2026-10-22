"""Surface FX: ISF shaders with a vertex stage (`fxVsFunc`) and a fragment stage (`fxColorForPixel`).

An FX folder holds `<Name>.fs` and `<Name>.vs`; the ISF header may sit in either file (Rutt Etra
keeps it in the `.vs`).  The interface the shipped FX rely on (from the "Empty Template" comment
block and the corpus survey, see `06-feature-inventory-and-clone.md`):

    vertex   in vec4 mm_Vertex (xy in -1..1, w = alpha), in vec4 mm_TexCoord0 (xy = input rect coord
             0..1, zw = surface coord 0..1); out vec2 mm_FragNormCoord, mm_SurfaceCoord; out float mm_Alpha;
             uniform mat4 mm_ModelViewProjectionMatrix, mm_TextureMatrix; main() initialises the outputs
             then calls fxVsFunc(), which must write gl_Position.
    fragment vec4 fxColorForPixel(vec2 mm_FragNormCoord); FX_NORM_PIXEL(uv), FX_IMG_SIZE(),
             FX_NORM_PIXEL_LOD(uv, lod), FX_TEXEL_FETCH(uv, lod); the media is also reachable as the
             ISF image `inputImage` (IMG_* macros).
    both     uniform vec4 mm_ModulationColor; int mm_BlendMode; bool mm_IsRenderingPreview; int mm_SurfaceIndex;
             BlendMode* defines, SURFACE_IS_<kind> define, RENDER_SETTINGS INSTANCE_COUNT (int or input name).
"""
from __future__ import annotations

import re
from pathlib import Path

from .assembly import (AssembledProgram, MACROS, DEFAULT_GLSL_VERSION, resolve_includes, _legacy_rewrites,
                       _default_literal)
from .header import IsfDocument, IsfError, parse_isf_source, split_header
from .inputs import IsfInput, InputType
from .material import Material, MaterialSource

BLEND_DEFINES = """#define BlendModeIgnoreAlpha 0
#define BlendModeAdd 1
#define BlendModeOver 2
#define BlendModeOverPremultiplied 3
#define BlendModeMultiply 4
#define BlendModeSubtract 5
#define BlendModeStencilLuma 6
#define BlendModeSilhouetteLuma 7
#define BlendModeSilhouetteAlpha 8
"""

FX_MACROS = """// FX macros
#define FX_NORM_PIXEL(uv) IMG_NORM_PIXEL(inputImage, (uv))
#define FX_IMG_SIZE() inputImage_size
#define FX_NORM_PIXEL_LOD(uv, lod) IMG_NORM_PIXEL_LOD(inputImage, (uv), (lod))
#define FX_TEXEL_FETCH(uv, lod) IMG_TEXEL_FETCH(inputImage, (uv), int(lod))
"""

MM_UNIFORMS = {
    "mm_ModelViewProjectionMatrix": "uniform mat4 mm_ModelViewProjectionMatrix;",
    "mm_TextureMatrix": "uniform mat4 mm_TextureMatrix;",
    "mm_ModulationColor": "uniform vec4 mm_ModulationColor;",
    "mm_BlendMode": "uniform int mm_BlendMode;",
    "mm_IsRenderingPreview": "uniform bool mm_IsRenderingPreview;",
    "mm_SurfaceIndex": "uniform int mm_SurfaceIndex;",
}

# Shared compositing used by the plain surface shader and by FX fragments: soft edge, layer mask,
# circle shape, modulation and blend-mode packing.
COMPOSITE_GLSL = """uniform vec4 modulation;      // rgb * opacity in a
uniform int softActive;
uniform vec4 softWidth;       // left, right, top, bottom
uniform vec4 softCurve;
uniform float softGamma;
uniform int blendMode;
uniform int shapeMode;        // 0 quad/triangle, 1 circle (inscribed ellipse of the local square)
uniform int hasMask;          // layer mask texture bound on unit 1 (alpha in .r, sampled at local coords)
uniform sampler2D maskTex;

float mm_edge(float d, float w, float curve) {
    if (w <= 0.0) return 1.0;
    float t = clamp(d / w, 0.0, 1.0);
    float k = pow(2.0, (curve - 0.5) * 4.0);
    return pow(t, k);
}

// Applies shape, mask, soft edge, modulation and blend packing to a sampled colour.
// Returns false when the fragment must be discarded.
bool mm_composite(inout vec4 c, vec2 local, float alphaIn) {
    float a = alphaIn;
    if (shapeMode == 1) {
        vec2 d = (local - 0.5) * 2.0;
        float r = length(d);
        float aa = fwidth(r) * 1.5;
        a *= 1.0 - smoothstep(1.0 - aa, 1.0, r);
        if (a <= 0.0) return false;
    }
    if (hasMask != 0) {
        a *= texture(maskTex, clamp(local, 0.0, 1.0)).r;
    }
    if (softActive != 0) {
        a *= mm_edge(local.x, softWidth.x, softCurve.x);
        a *= mm_edge(1.0 - local.x, softWidth.y, softCurve.y);
        a *= mm_edge(1.0 - local.y, softWidth.z, softCurve.z);
        a *= mm_edge(local.y, softWidth.w, softCurve.w);
        a = pow(a, softGamma);
    }
    c.rgb *= modulation.rgb;
    float alpha = (blendMode == 0 ? 1.0 : c.a) * modulation.a * a;
    if (blendMode == 3) { c = vec4(c.rgb * modulation.a * a, alpha); return true; }
    if (blendMode == 1 || blendMode == 5) { c = vec4(c.rgb * alpha, alpha); return true; }
    if (blendMode == 4) { c = vec4(mix(vec3(1.0), c.rgb, alpha), alpha); return true; }
    c = vec4(c.rgb, alpha);
    return true;
}
"""


class FxMaterial(Material):
    """A loaded Surface FX: ISF document plus the two stage bodies."""

    def __init__(self, source: MaterialSource, doc: IsfDocument, vs_body: str, fs_body: str, vs_path: Path):
        super().__init__(source, doc)
        self.vs_body = vs_body
        self.fs_body = fs_body
        self.vs_path = vs_path
        self.vs_mtime = vs_path.stat().st_mtime
        self.surface_kind = "quad"

    def assemble(self) -> AssembledProgram:
        defs = self.defines()
        key = dict(defs, __kind=self.surface_kind)   # type: ignore[arg-type]
        if self.program is None or key != self._program_defines:
            self.program = assemble_fx(self.doc, self.vs_body, self.fs_body, defines=defs,
                                       search_dirs=[self.source.folder], surface_kind=self.surface_kind)
            self._program_defines = key
        return self.program

    def needs_rebuild(self) -> bool:
        return self.program is None or dict(self.defines(), __kind=self.surface_kind) != self._program_defines  # type: ignore[arg-type]

    def source_changed_on_disk(self) -> bool:
        try:
            return (self.source.fragment_path.stat().st_mtime != self.mtime
                    or self.vs_path.stat().st_mtime != self.vs_mtime)
        except OSError:
            return False

    @property
    def instance_count_spec(self):
        return self.doc.render_settings.get("INSTANCE_COUNT")


def load_fx(path: str | Path) -> FxMaterial:
    folder = Path(path)
    if folder.is_file():
        folder = folder.parent
    if not folder.is_dir():
        raise IsfError(f"FX folder doesn't exist: {folder}")
    fs = sorted(folder.glob("*.fs"))
    vs = sorted(folder.glob("*.vs"))
    if len(fs) != 1:
        raise IsfError(f"FX folder {folder.name} must contain exactly one .fs file")
    if len(vs) != 1:
        raise IsfError(f"FX folder {folder.name} must contain exactly one .vs file")
    fs_text = fs[0].read_text(encoding="utf-8", errors="replace")
    vs_text = vs[0].read_text(encoding="utf-8", errors="replace")
    # Either file may carry the ISF header; inputs from both are merged (first definition wins).
    fs_doc = parse_isf_source(fs_text)
    vs_doc = parse_isf_source(vs_text)
    doc = fs_doc if fs_doc.header else vs_doc
    other = vs_doc if doc is fs_doc else fs_doc
    if other.header:
        names = {i.name for i in doc.inputs}
        doc.inputs += [i for i in other.inputs if i.name not in names]
        gnames = {g["NAME"] for g in doc.generators}
        doc.generators += [g for g in other.generators if g["NAME"] not in gnames]
        if not doc.render_settings:
            doc.render_settings = other.render_settings
        if not doc.media:
            doc.media = other.media
    if "fxColorForPixel" not in fs_doc.body:
        raise IsfError(f"{fs[0].name}: no fxColorForPixel() entry point")
    if "fxVsFunc" not in vs_doc.body:
        raise IsfError(f"{vs[0].name}: no fxVsFunc() entry point")
    thumb = next((folder / n for n in ("thumbnail.jpg", "thumbnail.jpeg", "thumbnail.png") if (folder / n).is_file()), None)
    src = MaterialSource(folder, fs[0], vs[0], thumb, folder.name)
    return FxMaterial(src, doc, vs_doc.body, fs_doc.body, vs[0])


_COMMENT_RE = re.compile(r"//.*?$|/\*.*?\*/", re.S | re.M)


def _declares_uniform(body: str, name: str) -> bool:
    code = _COMMENT_RE.sub("", body)
    return re.search(r"^\s*uniform\s+\w+\s+" + re.escape(name) + r"\s*;", code, re.M) is not None


def _common_preamble(doc: IsfDocument, version: str, defines: dict[str, int], surface_kind: str,
                     uses_time: bool, uses_mouse: bool, bodies: str) -> tuple[list[str], list[IsfInput], list[IsfInput], list[str]]:
    lines: list[str] = [f"#version {version}", f"#define SURFACE_IS_{surface_kind} 1", BLEND_DEFINES]
    for inp in doc.inputs:
        if inp.type == InputType.LONG and "generate_as_define" in inp.flags:
            idx = defines.get(inp.name, int(inp.default))
            if 0 <= idx < len(inp.values):
                ident = re.sub(r"[^A-Za-z0-9_]", "_", str(inp.values[idx]))
                lines.append(f"#define {inp.name}_IS_{ident} 1")
    lines.append("// Globals")
    if uses_time:
        lines += ["uniform float TIME;", "uniform float CLOCK_TIME;", "uniform vec4 DATE;",
                  "uniform float TIMEDELTA;", "uniform float FRAMEINDEX;"]
    lines += ["uniform int PASSINDEX=0;", "uniform vec2 RENDERSIZE;"]
    if uses_mouse:
        lines += ["uniform int MOUSEKEYSTATE;", "uniform vec2 MOUSEPOS;"]
    lines.append(MACROS)
    lines.append("// Input media")
    lines += ["uniform sampler2D inputImage;", "uniform vec2 inputImage_size=vec2(1024,1024);",
              "uniform ivec2 inputImage_mult=ivec2(1,1);", "uniform vec2 inputImage_add=vec2(0,0);"]
    lines.append(FX_MACROS)
    lines.append("// Surface uniforms")
    for name, decl in MM_UNIFORMS.items():
        if not _declares_uniform(bodies, name):
            lines.append(decl)
    lines.append("// Inputs")
    uniform_inputs: list[IsfInput] = []
    texture_inputs: list[IsfInput] = []
    for inp in doc.inputs:
        gt = inp.glsl_type
        if not gt:
            continue
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
    lines.append("// Generated Attributes")
    gen_names = [g["NAME"] for g in doc.generators]
    for g in gen_names:
        lines.append(f"uniform float {g} = 0.0;")
    return lines, uniform_inputs, texture_inputs, gen_names


def assemble_fx(doc: IsfDocument, vs_body: str, fs_body: str, *, defines: dict[str, int] | None = None,
                search_dirs: list[Path] | None = None, surface_kind: str = "quad",
                glsl_version: str | None = None) -> AssembledProgram:
    version = glsl_version or doc.glsl_version or DEFAULT_GLSL_VERSION
    vs_body = resolve_includes(_legacy_rewrites(vs_body), search_dirs or [])
    fs_body = resolve_includes(_legacy_rewrites(fs_body), search_dirs or [])
    both = vs_body + "\n" + fs_body
    uses_time = bool(re.search(r"\bTIME\b|\bCLOCK_TIME\b|\bTIMEDELTA\b", both))
    uses_mouse = bool(re.search(r"\bMOUSEPOS\b|\bMOUSEKEYSTATE\b", both))
    defines = defines or {}

    pre, uniform_inputs, texture_inputs, gen_names = _common_preamble(doc, version, defines, surface_kind,
                                                                      uses_time, uses_mouse, both)
    vertex = list(pre)
    vertex += ["in vec4 mm_Vertex;", "in vec4 mm_TexCoord0;",
               "out vec2 mm_FragNormCoord;", "out vec2 mm_SurfaceCoord;", "out float mm_Alpha;", "",
               "#line 1", vs_body, "",
               "void main() {",
               "    mm_FragNormCoord = (mm_TextureMatrix * vec4(mm_TexCoord0.xy, 0.0, 1.0)).xy;",
               "    mm_SurfaceCoord = mm_TexCoord0.zw;",
               "    mm_Alpha = mm_Vertex.w;",
               "    gl_Position = mm_ModelViewProjectionMatrix * vec4(mm_Vertex.xy, 0.0, 1.0);",
               "    fxVsFunc();",
               "}"]
    fragment = list(pre)
    fragment += ["in vec2 mm_FragNormCoord;", "in vec2 mm_SurfaceCoord;", "in float mm_Alpha;",
                 "out vec4 FragColor;", COMPOSITE_GLSL, ""]
    body_line_offset = len(fragment) + 1
    fragment += ["#line 1", fs_body, "",
                 "void main() {",
                 "    vec4 c = fxColorForPixel(mm_FragNormCoord);",
                 "    if (!mm_composite(c, mm_SurfaceCoord, mm_Alpha)) discard;",
                 "    FragColor = c;",
                 "}"]
    return AssembledProgram("\n".join(vertex) + "\n", "\n".join(fragment) + "\n", uniform_inputs, gen_names,
                            texture_inputs, [t.name for t in doc.imported], body_line_offset, uses_time, uses_mouse)
