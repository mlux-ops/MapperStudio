"""Locate and parse the ISF JSON header of a shader source.

The header is the first block comment `/*{ ... }*/`.  MadMapper's own shipped materials contain
trailing commas (e.g. `Fill.fs`), so the JSON is cleaned leniently before parsing: trailing commas
before `]`/`}` are removed and `//` line comments outside strings are stripped.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .inputs import IsfInput, parse_input, InputType


class IsfError(ValueError):
    """Invalid ISF header or shader."""


_TRAILING_COMMA = re.compile(r",(\s*[\]}])")
_BARE_TRAILING_DOT = re.compile(r"(?<![\w.])(-?\d+)\.(?![\d.\w])")   # 1.  -> 1.0
_BARE_LEADING_DOT = re.compile(r"(?<![\w.])(-?)\.(\d)")                # .5  -> 0.5


def _strip_line_comments(text: str) -> str:
    out: list[str] = []
    in_str = False
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
                out.append(c)
            elif c == "/" and i + 1 < n and text[i + 1] == "/":
                while i < n and text[i] != "\n":
                    i += 1
                continue
            else:
                out.append(c)
        i += 1
    return "".join(out)


def _fix_numbers(text: str) -> str:
    """Repair non-JSON number spellings (`1.`, `.5`) that MadMapper's shipped headers use, outside strings."""
    parts = text.split('"')
    for i in range(0, len(parts), 2):  # even indexes are outside string literals
        parts[i] = _BARE_LEADING_DOT.sub(r"\g<1>0.\g<2>", _BARE_TRAILING_DOT.sub(r"\g<1>.0", parts[i]))
    return '"'.join(parts)


def split_header(source: str) -> tuple[dict[str, Any], str, int]:
    """Return `(header_dict, body_source, body_start_line)`.

    A source without a header is accepted as an empty header (plain GLSL material).
    """
    # The directive is the first block comment that starts with "{"; ordinary comments before it
    # are skipped (the FX "Empty Template" documents the interface in a comment above its header).
    pos = 0
    raw = ""
    end = -1
    while True:
        if not source[pos:].lstrip().startswith("/*"):
            return {}, source, 1
        start = source.index("/*", pos)
        end = source.find("*/", start)
        if end < 0:
            raise IsfError("unterminated ISF header comment")
        raw = source[start + 2:end].strip()
        if raw.startswith("{"):
            break
        pos = end + 2
    body = source[end + 2:]
    body_line = source[:end + 2].count("\n") + 1
    cleaned = _fix_numbers(_TRAILING_COMMA.sub(r"\1", _strip_line_comments(raw)))
    try:
        header = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise IsfError(f"ISF directive is not valid JSON: {exc.msg} (line {exc.lineno})") from exc
    if not isinstance(header, dict):
        raise IsfError("ISF directive must be a JSON object")
    return header, body, body_line


@dataclass
class ImportedTexture:
    name: str
    path: str | list[str]
    kind: str = "2D"
    min_filter: str = "LINEAR"
    mag_filter: str = "LINEAR"
    wrap: str = "CLAMP_TO_EDGE"


@dataclass
class IsfDocument:
    """Everything parsed from one shader source."""
    header: dict[str, Any]
    body: str
    body_line: int
    inputs: list[IsfInput] = field(default_factory=list)
    generators: list[dict[str, Any]] = field(default_factory=list)
    imported: list[ImportedTexture] = field(default_factory=list)
    description: str = ""
    credit: str = ""
    version: str = ""
    categories: list[str] = field(default_factory=list)
    tags: str = ""
    glsl_version: str | None = None
    render_settings: dict[str, Any] = field(default_factory=dict)
    rasterisation_settings: dict[str, Any] = field(default_factory=dict)
    media: dict[str, Any] = field(default_factory=dict)
    min_madmapper_version: str = ""

    def input(self, name: str) -> IsfInput | None:
        return next((i for i in self.inputs if i.name == name), None)

    def input_by_label(self, label: str) -> IsfInput | None:
        return next((i for i in self.inputs if i.label == label), None)

    @property
    def default_render_size(self) -> tuple[int, int]:
        rs = self.rasterisation_settings
        return int(rs.get("DEFAULT_WIDTH", 1024)), int(rs.get("DEFAULT_HEIGHT", 1024))

    @property
    def requires_last_frame(self) -> bool:
        return bool(self.rasterisation_settings.get("REQUIRES_LAST_FRAME", False))


_VALID_RENDER_KEYS = {
    "INSTANCE_COUNT", "POINT_COUNT", "INDEX_COUNT", "DEPTH_TESTING", "DEPTH_FUNC", "BLEND_EQUATION",
    "BLEND_SRC", "BLEND_DST", "CLAMP_MATERIAL_OUTPUT", "TREAT_AS_ILDA_FRAME", "CULLING", "FACE_CULLING",
}
_VALID_RASTER_KEYS = {
    "DEFAULT_RENDER_TO_TEXTURE", "DEFAULT_WIDTH", "DEFAULT_HEIGHT", "DEFAULT_PIXEL_FORMAT",
    "REQUIRES_LAST_FRAME", "REQUIRES_LAST_FRAME_MIPMAPPING",
}


def parse_isf_source(source: str) -> IsfDocument:
    header, body, body_line = split_header(source)
    doc = IsfDocument(header, body, body_line)

    inputs_raw: list[Any] = []
    for key in ("INPUTS", "PARAMETERS"):
        val = header.get(key)
        if isinstance(val, list):
            inputs_raw.extend(val)
    names: set[str] = set()
    for item in inputs_raw:
        if not isinstance(item, dict):
            continue  # MadMapper silently ignores non-object entries
        inp = parse_input(item)
        if inp.name in names:
            raise IsfError(f"duplicate ISF INPUT name {inp.name!r}")
        names.add(inp.name)
        doc.inputs.append(inp)

    gens = header.get("GENERATORS")
    if isinstance(gens, list):
        for g in gens:
            if not isinstance(g, dict):
                continue
            if not isinstance(g.get("NAME"), str) or not g["NAME"]:
                raise IsfError("GENERATOR without a NAME")
            if not isinstance(g.get("TYPE"), str):
                raise IsfError(f"GENERATOR {g['NAME']}: TYPE must be a string")
            if g["NAME"] in names:
                raise IsfError(f"GENERATOR {g['NAME']!r} clashes with an INPUT name")
            names.add(g["NAME"])
            params = g.get("PARAMS", g.get("FILTERS", {}))
            if params is None:
                params = {}
            if not isinstance(params, dict):
                raise IsfError(f"GENERATOR {g['NAME']}: PARAMS must be an object")
            doc.generators.append({"NAME": g["NAME"], "TYPE": g["TYPE"], "PARAMS": params})

    imported = header.get("IMPORTED")
    if isinstance(imported, list):
        for t in imported:
            if isinstance(t, dict) and isinstance(t.get("NAME"), str) and t.get("PATH"):
                doc.imported.append(ImportedTexture(t["NAME"], t["PATH"], str(t.get("TYPE", "2D")),
                                                    str(t.get("GL_TEXTURE_MIN_FILTER", "LINEAR")),
                                                    str(t.get("GL_TEXTURE_MAG_FILTER", "LINEAR")),
                                                    str(t.get("GL_TEXTURE_WRAP", "CLAMP_TO_EDGE"))))
    elif isinstance(imported, dict):  # classic ISF: {NAME: {PATH: ...}}
        for name, t in imported.items():
            if isinstance(t, dict) and t.get("PATH"):
                doc.imported.append(ImportedTexture(str(name), t["PATH"], str(t.get("TYPE", "2D")),
                                                    str(t.get("GL_TEXTURE_MIN_FILTER", "LINEAR")),
                                                    str(t.get("GL_TEXTURE_MAG_FILTER", "LINEAR")),
                                                    str(t.get("GL_TEXTURE_WRAP", "CLAMP_TO_EDGE"))))

    doc.description = str(header.get("DESCRIPTION", "") or "")
    doc.credit = str(header.get("CREDIT", "") or "")
    vsn = header.get("VSN", header.get("VERSION", ""))
    doc.version = str(vsn) if vsn is not None else ""
    cats = header.get("CATEGORIES")
    if isinstance(cats, list):
        doc.categories = [str(c) for c in cats]
    tags = header.get("TAGS")
    doc.tags = tags if isinstance(tags, str) else ""   # an array is ignored, as in MadMapper
    doc.min_madmapper_version = str(header.get("MADMAPPER_MIN_VERSION", "") or "")
    gv = header.get("GLSL_VERSION")
    if gv is not None:
        if not isinstance(gv, str):
            raise IsfError("GLSL_VERSION must be a string")
        doc.glsl_version = gv

    rs = header.get("RENDER_SETTINGS")
    if isinstance(rs, dict):
        for k in rs:
            if k not in _VALID_RENDER_KEYS:
                raise IsfError(f"Unhandled key in ISF header RENDER_SETTINGS: {k}")
        doc.render_settings = dict(rs)
    ras = header.get("RASTERISATION_SETTINGS")
    if isinstance(ras, dict):
        for k, v in ras.items():
            if k not in _VALID_RASTER_KEYS:
                raise IsfError(f"Unhandled key in ISF header RASTERISATION_SETTINGS: {k}")
            if k in ("DEFAULT_WIDTH", "DEFAULT_HEIGHT") and not (isinstance(v, int) and 1 <= v <= 32768):
                raise IsfError(f"RASTERISATION_SETTINGS {k} must be an integer between 1 and 32768")
        doc.rasterisation_settings = dict(ras)
    media = header.get("MEDIA")
    if isinstance(media, dict):
        if "REQUIRES_TEXTURE" in media and not isinstance(media["REQUIRES_TEXTURE"], bool):
            raise IsfError("MEDIA REQUIRES_TEXTURE must be a boolean")
        doc.media = dict(media)

    # Generator parameter references must resolve to an input or another generator.
    known = {i.name for i in doc.inputs} | {g["NAME"] for g in doc.generators}
    for g in doc.generators:
        for pname, pval in g["PARAMS"].items():
            if isinstance(pval, str) and pval not in known and not pval.startswith("/") \
                    and pname not in ("shape", "type"):
                # MadMapper allows enum strings for some params ("shape": "In"); anything else
                # must name an input, generator or channel URL.
                if pname in _ENUM_PARAMS:
                    continue
                raise IsfError(f"Error parsing generated {g['NAME']}: parameter {pname} references "
                               f"unknown input {pval!r}")
    return doc


_ENUM_PARAMS = {"shape", "type", "ease"}
