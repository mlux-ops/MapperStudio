"""`Material`: an ISF material loaded from a folder (or a single `.fs` file).

Folder rules follow MadMapper's loader (`03-materials-isf.md`): exactly one `.fs`, at most one
`.vs` (ignored here: the vertex stage is fixed), optional `.info` and `thumbnail.*`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .assembly import AssembledProgram, assemble_material
from .generators import Generator, GeneratorContext, build_generator
from .header import IsfDocument, IsfError, parse_isf_source
from .inputs import InputError, InputType, IsfInput


@dataclass
class MaterialSource:
    folder: Path
    fragment_path: Path
    vertex_path: Path | None
    thumbnail_path: Path | None
    name: str


def locate_material(path: str | Path) -> MaterialSource:
    p = Path(path)
    if p.is_file() and p.suffix.lower() == ".fs":
        folder = p.parent
        fs = [p]
    elif p.is_dir():
        folder = p
        fs = sorted(x for x in folder.iterdir() if x.suffix == ".fs")
    else:
        raise IsfError(f"Error creating material, folder doesn't exist: {p}")
    if not fs:
        raise IsfError(f"No fragment shader file in folder {folder}")
    if len(fs) > 1:
        raise IsfError(f"Multiple fragment shader files in folder {folder}")
    vs = sorted(x for x in folder.iterdir() if x.suffix == ".vs")
    if len(vs) > 1:
        raise IsfError(f"Multiple vertex shader files in folder {folder}")
    thumb = next((folder / n for n in ("thumbnail.jpg", "thumbnail.jpeg", "thumbnail.png") if (folder / n).is_file()), None)
    return MaterialSource(folder, fs[0], vs[0] if vs else None, thumb, fs[0].stem)


class Material:
    """A parsed material with live parameter values and generator state (no GL objects)."""

    def __init__(self, source: MaterialSource, doc: IsfDocument):
        self.source = source
        self.doc = doc
        self.name = source.name
        self.values: dict[str, Any] = {i.name: _copy(i.default) for i in doc.inputs}
        self.generators: list[Generator] = [build_generator(g) for g in doc.generators]
        self.ctx = GeneratorContext()
        self._started = time.perf_counter()
        self._last = self._started
        self._frame = 0
        self.program: AssembledProgram | None = None
        self._program_defines: dict[str, int] = {}
        self.mtime = source.fragment_path.stat().st_mtime

    # ---- parameters ----
    @property
    def inputs(self) -> list[IsfInput]:
        return self.doc.inputs

    def input(self, name: str) -> IsfInput | None:
        return self.doc.input(name)

    def set_value(self, name: str, value: Any) -> None:
        inp = self.doc.input(name)
        if inp is None:
            raise InputError(f"material {self.name} has no input {name!r}")
        self.values[name] = inp.coerce(value)

    def set_value_by_label(self, label: str, value: Any) -> bool:
        inp = self.doc.input_by_label(label)
        if inp is None:
            return False
        self.set_value(inp.name, value)
        return True

    def apply_values(self, values: dict[str, Any], *, by_label: bool = False) -> list[str]:
        """Apply a dict of values; returns the keys that did not match an input."""
        missing: list[str] = []
        for k, v in values.items():
            if k.startswith("__"):
                continue
            try:
                ok = self.set_value_by_label(k, v) if by_label else (self.doc.input(k) is not None and (self.set_value(k, v) or True))
            except InputError:
                ok = False
            if not ok:
                missing.append(k)
        return missing

    def defines(self) -> dict[str, int]:
        return {i.name: int(self.values[i.name]) for i in self.doc.inputs
                if i.type == InputType.LONG and "generate_as_define" in i.flags}

    # ---- per-frame ----
    def tick(self, bpm: float, now: float | None = None) -> None:
        now = time.perf_counter() if now is None else now
        dt = max(0.0, min(0.25, now - self._last))
        self._last = now
        self._frame += 1
        self.ctx.time = now - self._started
        self.ctx.dt = dt
        self.ctx.bpm = bpm
        self.ctx.values = dict(self.values)
        for g in self.generators:
            self.ctx.values[g.name] = g.update(self.ctx)

    def generator_values(self) -> dict[str, float]:
        return {g.name: g.value for g in self.generators}

    @property
    def time(self) -> float:
        return self.ctx.time

    @property
    def frame_index(self) -> int:
        return self._frame

    def restart(self) -> None:
        self._started = self._last = time.perf_counter()
        self._frame = 0
        for g in self.generators:
            g.reset()

    # ---- GLSL ----
    def assemble(self) -> AssembledProgram:
        """(Re)build the GLSL sources if the generate_as_define selection changed."""
        defs = self.defines()
        if self.program is None or defs != self._program_defines:
            self.program = assemble_material(
                self.doc, self.doc.body, defines=defs, search_dirs=[self.source.folder],
                requires_last_frame=self.doc.requires_last_frame)
            self._program_defines = defs
        return self.program

    def needs_rebuild(self) -> bool:
        return self.program is None or self.defines() != self._program_defines

    def source_changed_on_disk(self) -> bool:
        try:
            return self.source.fragment_path.stat().st_mtime != self.mtime
        except OSError:
            return False


def load_material(path: str | Path) -> Material:
    src = locate_material(path)
    text = src.fragment_path.read_text(encoding="utf-8", errors="replace")
    try:
        doc = parse_isf_source(text)
    except (IsfError, InputError) as exc:
        raise IsfError(f"{src.fragment_path.name}: {exc}") from exc
    if "materialColorForPixel" not in doc.body and "fxColorForPixel" not in doc.body:
        raise IsfError(f"{src.fragment_path.name}: no materialColorForPixel() entry point")
    return Material(src, doc)


def _copy(v: Any) -> Any:
    return list(v) if isinstance(v, list) else v
