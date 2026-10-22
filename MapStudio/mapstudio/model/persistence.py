"""Save / load MapStudio projects as JSON (`*.mapstudio`).

Media paths are stored relative to the project file when the media lives next to it, so a
project folder can be moved as a whole (the same idea as MadMapper's `.madproject` folder).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .project import Project, ProjectError, VisualKind

PROJECT_SUFFIX = ".mapstudio"


def _relativise(project_dir: Path, source: str) -> str:
    try:
        p = Path(source)
        if p.is_absolute():
            rel = os.path.relpath(p, project_dir)
            if not rel.startswith(".."):
                return rel.replace("\\", "/")
    except ValueError:
        pass  # different drive
    return source


def _absolutise(project_dir: Path, source: str) -> str:
    p = Path(source)
    if not p.is_absolute() and source:
        return str((project_dir / source).resolve())
    return source


def save_project(project: Project, path: str | Path) -> None:
    path = Path(path)
    if path.suffix.lower() != PROJECT_SUFFIX:
        path = path.with_suffix(PROJECT_SUFFIX)
    project_dir = path.parent.resolve()
    data = project.to_dict()
    for v in data["visuals"]:
        if v["kind"] in (VisualKind.IMAGE.value, VisualKind.MOVIE.value, VisualKind.MATERIAL.value):
            v["source"] = _relativise(project_dir, v["source"])
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    project.path = str(path)


def load_project(path: str | Path) -> Project:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise ProjectError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProjectError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProjectError(f"{path}: top level must be an object")
    project = Project.from_dict(data)
    project_dir = path.parent.resolve()
    for v in project.visuals:
        if v.kind in (VisualKind.IMAGE, VisualKind.MOVIE, VisualKind.MATERIAL):
            v.source = _absolutise(project_dir, v.source)
    project.path = str(path)
    return project
