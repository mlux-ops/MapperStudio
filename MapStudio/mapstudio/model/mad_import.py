"""Import a MadMapper `.madproject` / `.mad` into a MapStudio `Project`.

What is carried over (everything else is reported in `ImportReport.skipped`):

* video outputs (centre, stage size, pixel size, loopback buffers);
* `quad` and `circle` surfaces: output corners, input uvs, visual link, visibility, lock,
  opacity, blend mode, modulation colour, perspective flag, soft-edge, mesh warp grid;
* visuals: images, movies (path resolved against the project folder), materials (ISF folder
  inside the project's `Media/Materials`, else the MadMapper library, else by name),
  loopback live inputs (`/camera/loopback/video/N`), the factory TestCard and Solid Color
  generators (mapped to the built-ins); material parameter values keyed by their ISF label.

Key names and the layout of the binary blobs come from `02-project-schema.md`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..madfile import read_mad_file, decode_polygonf_blob, unwrap, MadFileError
from ..madfile.qvariant_stream import QVariantStreamReader, StreamError
from .project import Project, Output, QuadSurface, Visual, VisualKind, BlendMode, SoftEdge, Point, Shape, reserve_ids

import os

# Where the MadMapper material / FX library may live. The MADMAPPER_RESOURCES environment variable
# (path of MadMapper's "Resources" folder) takes precedence on any platform.
MADMAPPER_LIBRARY_CANDIDATES = [
    *([Path(os.environ["MADMAPPER_RESOURCES"])] if os.environ.get("MADMAPPER_RESOURCES") else []),
    Path(r"E:\Games\MadMapperDemo 6.1.8\Resources"),
    Path(r"C:\Program Files\MadMapper\Resources"),
    Path("/Applications/MadMapper.app/Contents/Resources"),
    Path("/Applications/MadMapper Demo.app/Contents/Resources"),
    Path.home() / "Applications" / "MadMapper.app" / "Contents" / "Resources",
]


@dataclass
class ImportReport:
    source: str
    file_version: int = 0
    imported: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"Imported {self.source} (file version {self.file_version})"]
        lines += [f"  + {s}" for s in self.imported]
        lines += [f"  - skipped: {s}" for s in self.skipped]
        lines += [f"  ! {s}" for s in self.warnings]
        return "\n".join(lines)


def _rgba(v: Any) -> tuple[float, float, float, float]:
    if isinstance(v, dict) and "rgba" in v:
        r, g, b, a = v["rgba"]
        return float(r), float(g), float(b), float(a)
    return 1.0, 1.0, 1.0, 1.0


def _decode_warp_grid(blob: bytes, cols: int, rows: int) -> list[Point] | None:
    """`warping_positions`: a QDataStream payload holding (cols+1)*(rows+1) QPointF.

    MadMapper writes a `QList<QPointF>` (quint32 count, then doubles).  Some files prefix the
    grid with the size again; both layouts are accepted.
    """
    want = (cols + 1) * (rows + 1)
    r = QVariantStreamReader(blob)
    try:
        n = r.read_u32()
        if n == want:
            pts = [r.read_qpointf() for _ in range(n)]
            return pts
        # alternative layout: QSize then the list
        r.pos = 0
        w, h = r.read_qsize()
        n = r.read_u32()
        if (w + 1) * (h + 1) == n == want:
            return [r.read_qpointf() for _ in range(n)]
    except StreamError:
        return None
    return None


def _material_folder(url: str, project_dir: Path) -> str:
    """Resolve `/materials/<Name>` to a folder on disk (project media first, then the library)."""
    name = url.split("/materials/", 1)[1] if "/materials/" in url else url.strip("/")
    for base in [project_dir / "Media" / "Materials", *[c / "Materials" for c in MADMAPPER_LIBRARY_CANDIDATES]]:
        cand = base / name
        if cand.is_dir():
            return str(cand)
    return name  # unresolved: keep the name so the user can relink


def import_mad_project(path: str | Path) -> tuple[Project, ImportReport]:
    path = Path(path)
    project_dir = path if path.is_dir() else path.parent
    report = ImportReport(str(path))
    try:
        version, root_raw = read_mad_file(path)
    except MadFileError as exc:
        raise MadFileError(f"{path.name}: {exc}") from exc
    root = unwrap(root_raw)
    report.file_version = version
    project = Project(name=path.stem.replace(".madproject", ""))
    project.notes = str(root.get("notes") or "")
    project.master_level = float(root.get("masterLevel", 1.0))
    mcp = root.get("masterCustomParameters") or {}
    if isinstance(mcp.get("Global BPM/BPM"), (int, float)):
        project.bpm = float(mcp["Global BPM/BPM"])

    # ---- outputs -------------------------------------------------------------------------
    outputs_map = root.get("outputs") or {}
    outputs_list = outputs_map.get("outputs", []) if isinstance(outputs_map, dict) else outputs_map
    loopback_by_index: dict[int, int] = {}   # MadMapper output id -> our output id
    for o in outputs_list:
        if not isinstance(o, dict):
            continue
        otype = o.get("outputType", "Video")
        if otype != "Video":
            report.skipped.append(f"output {o.get('name')!r} of type {otype}")
            continue
        geom = o.get("geometry") or (0, 0, 1920, 1080)
        dgeom = o.get("dgeometry")
        px = (int(geom[2]), int(geom[3]))
        if dgeom and o.get("screenType", 0) == 0 and o.get("buffer"):
            px = (int(dgeom[2]), int(dgeom[3]))
        out = Output(int(o.get("id", 0)) or len(project.outputs) + 1, str(o.get("name", "Output")),
                     tuple(map(float, o.get("position", (0.0, 0.0)))),   # type: ignore[arg-type]
                     tuple(map(float, o.get("stageSize", (6.4, 3.6)))),  # type: ignore[arg-type]
                     px, "", bool(o.get("active", True)), bool(o.get("showTestPattern", False)),
                     bool(o.get("buffer", False)) or str(o.get("name", "")).lower() == "loopback")
        project.outputs.append(out)
        loopback_by_index[int(o.get("id", 0))] = out.id
        report.imported.append(f"output {out.name} ({px[0]}x{px[1]}, {'buffer' if out.is_buffer else 'screen'})")
    if not project.outputs:
        project.add_output("Output-1")
        report.warnings.append("no video outputs in the file; created a default one")

    # ---- visuals -------------------------------------------------------------------------
    visuals_map = root.get("visuals") or {}
    visuals_list = visuals_map.get("visuals", []) if isinstance(visuals_map, dict) else visuals_map
    for v in visuals_list:
        if not isinstance(v, dict):
            continue
        vid = int(v.get("id", 0))
        name = str(v.get("name") or f"Visual-{vid}")
        url = str(v.get("url") or "")
        mmtype = str(v.get("mmtype") or "")
        attrs = v.get("attributes") or {}
        vis: Visual | None = None
        if mmtype == "Materials" or url.startswith("/materials/"):
            vis = Visual(vid, name, VisualKind.MATERIAL, _material_folder(url, project_dir))
            vis.attributes = {k: (list(_rgba(val)) if isinstance(val, dict) else val)
                              for k, val in attrs.items() if not k.startswith(("Material/", "HAS_AUDIO", "audio_"))}
            vis.attributes["__by_label__"] = True
            vis.render_width = int(attrs.get("Material/Texture Width", 1024))
            vis.render_height = int(attrs.get("Material/Texture Height", 1024))
        elif mmtype in ("Movies", "Images") or url.startswith("./"):
            src = (project_dir / url).resolve() if url.startswith("./") else Path(url)
            kind = VisualKind.MOVIE if mmtype == "Movies" else VisualKind.IMAGE
            vis = Visual(vid, name, kind, str(src))
            vis.loop = str(attrs.get("looping_mode", "Loop")) != "Once"
            vis.speed = float(attrs.get("speed", 1.0) or 1.0)
            if not src.exists():
                report.warnings.append(f"media file missing: {src}")
        elif url.startswith("/camera/loopback/video/"):
            idx = int(url.rsplit("/", 1)[1])
            target = loopback_by_index.get(idx)
            if target is None:
                report.skipped.append(f"loopback visual {name!r} (no output {idx})")
                continue
            vis = Visual(vid, name, VisualKind.OUTPUT_LOOPBACK, str(target))
        elif url == "/generator/TestCard":
            vis = Visual(vid, name, VisualKind.TEST_CARD, "")
            vis.attributes = {
                "divisions_x": int(attrs.get("Divisions X", 4)), "divisions_y": int(attrs.get("Divisions Y", 4)),
                "front_color": list(_rgba(attrs.get("Color/Front Color"))),
                "back_color": list(_rgba(attrs.get("Color/Back Color"))),
            }
        elif url == "/generator/Solid Color":
            vis = Visual(vid, name, VisualKind.SOLID, "")
            vis.attributes = {"color": list(_rgba(attrs.get("Color") or attrs.get("Color/Color")))}
        else:
            report.skipped.append(f"visual {name!r} ({mmtype or 'unknown'}: {url})")
            continue
        project.visuals.append(vis)
        report.imported.append(f"visual {vis.name} [{vis.kind.value}]")

    # ---- surfaces ------------------------------------------------------------------------
    # `surfacesRelations[i]` is the index of surface i's parent group (-1 = top level).  Groups
    # are flattened; a hidden group hides its children (MadMapper toggles the whole group).
    raw_surfaces = [s for s in (root.get("surfaces") or []) if isinstance(s, dict)]
    relations = root.get("surfacesRelations") or []

    def effective_visible(index: int) -> bool:
        seen = 0
        while 0 <= index < len(raw_surfaces) and seen < 64:
            if not bool(raw_surfaces[index].get("visible", True)):
                return False
            index = int(relations[index]) if index < len(relations) else -1
            seen += 1
        return True

    for index, s in enumerate(raw_surfaces):
        stype = str(s.get("type", ""))
        name = str(s.get("name") or stype)
        if stype == "group":
            continue  # flattened: children carry their own geometry
        if stype not in ("quad", "circle", "triangle", "mask"):
            report.skipped.append(f"surface {name!r} of type {stype}")
            continue
        try:
            corners = decode_polygonf_blob(s.get("positions"))
            uvs = decode_polygonf_blob(s.get("uvs"))
        except MadFileError as exc:
            report.skipped.append(f"surface {name!r}: {exc}")
            continue
        shape = {"quad": Shape.QUAD, "circle": Shape.CIRCLE, "triangle": Shape.TRIANGLE, "mask": Shape.MASK}[stype]
        if shape == Shape.TRIANGLE:
            if len(corners) != 3:
                report.skipped.append(f"surface {name!r}: triangle with {len(corners)} corners")
                continue
            if len(uvs) != 3:
                uvs = [(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)]
        elif shape == Shape.MASK:
            if len(corners) < 3:
                report.skipped.append(f"surface {name!r}: mask with {len(corners)} points")
                continue
            uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        else:
            if len(corners) != 4:
                report.skipped.append(f"surface {name!r}: {len(corners)} corners")
                continue
            if len(uvs) != 4:
                uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        try:
            blend = BlendMode(int(s.get("blendMode", 2)))
        except ValueError:
            blend = BlendMode.OVER
        rgba = _rgba(s.get("modulation"))
        quad = QuadSurface(int(s.get("surfaceId", 0)) or 0, name, [tuple(p) for p in corners],
                           [tuple(p) for p in uvs], s.get("visualId") if int(s.get("visualId", -1)) >= 0 else None,
                           effective_visible(index), bool(s.get("locked", False)),
                           float(s.get("opacity", 1.0)), blend, rgba[:3],
                           bool(s.get("isPerspective", True)))
        quad.shape = shape
        flip = int(s.get("uvFlip", 0) or 0)
        quad.flip_h, quad.flip_v = bool(flip & 1), bool(flip & 2)
        # Surface FX live in customSettings: FX/Active, FX/Name, FX/<Name>/<Label> (label-keyed values).
        cs = s.get("customSettings") or {}
        fx_name = str(cs.get("FX/Name") or "")
        if fx_name and shape != Shape.MASK:
            prefix = f"FX/{fx_name}/"
            local_fx = project_dir / "FX" / "Surface2DFX" / fx_name
            # project-local FX keep their absolute folder so the project can be saved elsewhere
            quad.fx_name = str(local_fx) if local_fx.is_dir() else fx_name
            quad.fx_active = bool(cs.get("FX/Active", False))
            quad.fx_params = {k[len(prefix):]: (list(_rgba(v)) if isinstance(v, dict) else (list(v) if isinstance(v, tuple) else v))
                              for k, v in cs.items() if k.startswith(prefix)}
            quad.fx_params["__by_label__"] = True
        # Layer mask (quad loader): `mask` map with a `positions` polygon and `polygonInverted`.
        if s.get("maskEnabled") and isinstance(s.get("mask"), dict):
            try:
                mpts = decode_polygonf_blob(s["mask"].get("positions"))
            except MadFileError:
                mpts = []
            if len(mpts) >= 3:
                quad.mask_points = [tuple(p) for p in mpts]
                quad.mask_inverted = bool(s["mask"].get("polygonInverted", False))
                report.warnings.append(f"surface {name!r}: layer mask imported assuming surface-local coordinates")
        quad.soft_edge = SoftEdge(
            bool(s.get("softEdgeActive", False)),
            float(s.get("softEdgeLeftWidth", 0.0)), float(s.get("softEdgeRightWidth", 0.0)),
            float(s.get("softEdgeTopWidth", 0.0)), float(s.get("softEdgeBottomWidth", 0.0)),
            float(s.get("softEdgeLeftCurve", 0.5)), float(s.get("softEdgeRightCurve", 0.5)),
            float(s.get("softEdgeTopCurve", 0.5)), float(s.get("softEdgeBottomCurve", 0.5)),
            float(s.get("softEdgeGamma", 1.8)))
        if s.get("warpingEnabled") and s.get("warping_positions") and s.get("warping_size"):
            cols, rows = int(s["warping_size"][0]), int(s["warping_size"][1])
            pts = _decode_warp_grid(s["warping_positions"], cols, rows)
            if pts:
                quad.warp_cols, quad.warp_rows, quad.warp_points = cols, rows, pts
            else:
                report.warnings.append(f"surface {name!r}: mesh warp grid not decoded, using corner pin")
        if shape == Shape.MASK:
            quad.perspective = False
        if quad.id == 0:
            quad.id = 100000 + len(project.surfaces)
        project.surfaces.append(quad)
        report.imported.append(f"surface {quad.name}")

    # MadMapper lists surfaces foreground-first ("the first surface in your list will be in the
    # foreground", UI guide); MapStudio draws its list bottom-first, so reverse the order.
    project.surfaces.reverse()
    # MadMapper's visual ids are small ints; make sure new ids never collide with them.
    reserve_ids(project.max_id())
    _dedupe_ids(project, report)
    return project, report


def _dedupe_ids(project: Project, report: ImportReport) -> None:
    """Ids come from three separate MadMapper namespaces; MapStudio uses one. Reassign clashes."""
    seen: set[int] = set()
    next_free = project.max_id() + 1
    for out in project.outputs:
        if out.id in seen:
            old, out.id = out.id, next_free
            next_free += 1
            for v in project.visuals:
                if v.kind == VisualKind.OUTPUT_LOOPBACK and v.source == str(old):
                    v.source = str(out.id)
        seen.add(out.id)
    for v in project.visuals:
        if v.id in seen:
            old, v.id = v.id, next_free
            next_free += 1
            for s in project.surfaces:
                if s.visual_id == old:
                    s.visual_id = v.id
        seen.add(v.id)
    for s in project.surfaces:
        if s.id in seen:
            s.id = next_free
            next_free += 1
        seen.add(s.id)
    reserve_ids(next_free)
    for s in project.surfaces:
        if s.visual_id is not None and project.visual(s.visual_id) is None:
            report.warnings.append(f"surface {s.name!r} referenced visual {s.visual_id} which was not imported")
            s.visual_id = None


_MAD_NAME = re.compile(r"\.madproject$", re.IGNORECASE)
