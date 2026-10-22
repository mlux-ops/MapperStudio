"""The MapStudio project model.

Coordinate conventions (chosen to match what the MadMapper sample projects store, see
`02-project-schema.md`):

* **Stage space** is one shared 2D plane, y up. Every output is an axis-aligned rectangle
  in that plane (centre + size); a 16:9 output is 6.4 x 3.6 units by default.
* A surface's *output geometry* (`corners`) is four stage-space points in the order
  bottom-left, bottom-right, top-right, top-left.
* A surface's *input geometry* (`uv_corners`) is four points in media space, 0..1 on both
  axes with (0, 0) the bottom-left of the media, in the same corner order.
* A surface is drawn by every output whose rectangle it touches.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field, replace
from enum import IntEnum, Enum
from typing import Any, Iterator

Point = tuple[float, float]


class ProjectError(ValueError):
    """Invalid project data."""


class BlendMode(IntEnum):
    """Numbering follows MadMapper's `mm_BlendMode` definitions."""
    IGNORE_ALPHA = 0
    ADD = 1
    OVER = 2
    OVER_PREMULTIPLIED = 3
    MULTIPLY = 4
    SUBTRACT = 5
    STENCIL_LUMA = 6
    SILHOUETTE_LUMA = 7
    SILHOUETTE_ALPHA = 8


class VisualKind(str, Enum):
    IMAGE = "image"          # a still picture file
    MOVIE = "movie"          # a video file (Qt Multimedia)
    MATERIAL = "material"    # an ISF material folder or .fs file
    SOLID = "solid"          # built-in solid colour
    TEST_CARD = "test_card"  # built-in test card generator
    OUTPUT_LOOPBACK = "output_loopback"  # the rendered content of another output (video buffer)


_ids = itertools.count(1)


def next_id() -> int:
    return next(_ids)


def reserve_ids(upto: int) -> None:
    """Make sure freshly generated ids are larger than `upto` (after loading a project)."""
    global _ids
    current = next(_ids)
    _ids = itertools.count(max(current, upto + 1))


@dataclass
class SoftEdge:
    """Edge blending: per-side width (fraction of the surface, 0..1), curve (0..1, 0.5 = linear)
    and a gamma applied to the fade. Mirrors MadMapper's `softEdge*` keys."""
    active: bool = False
    left: float = 0.0
    right: float = 0.0
    top: float = 0.0
    bottom: float = 0.0
    left_curve: float = 0.5
    right_curve: float = 0.5
    top_curve: float = 0.5
    bottom_curve: float = 0.5
    gamma: float = 1.8

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "widths": [self.left, self.right, self.top, self.bottom],
            "curves": [self.left_curve, self.right_curve, self.top_curve, self.bottom_curve],
            "gamma": self.gamma,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SoftEdge":
        w = d.get("widths", [0, 0, 0, 0])
        c = d.get("curves", [0.5, 0.5, 0.5, 0.5])
        return cls(bool(d.get("active", False)), *map(float, w), *map(float, c), float(d.get("gamma", 1.8)))


@dataclass
class Visual:
    """A media item in the media panel."""
    id: int
    name: str
    kind: VisualKind
    source: str = ""                      # file path (relative to the project file when possible), material folder, or output id
    attributes: dict[str, Any] = field(default_factory=dict)   # ISF input values by input NAME; solid colour as "color"
    render_width: int = 1024              # material render-to-texture size
    render_height: int = 1024
    loop: bool = True                     # movies
    speed: float = 1.0                    # movies
    thumbnail_png: bytes | None = None    # optional cached thumbnail

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id, "name": self.name, "kind": self.kind.value, "source": self.source,
            "attributes": _jsonable(self.attributes),
            "render_size": [self.render_width, self.render_height],
            "loop": self.loop, "speed": self.speed,
        }
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Visual":
        try:
            kind = VisualKind(d["kind"])
        except (KeyError, ValueError) as exc:
            raise ProjectError(f"visual {d.get('id')}: unknown kind {d.get('kind')!r}") from exc
        rw, rh = d.get("render_size", [1024, 1024])
        return cls(int(d["id"]), str(d.get("name", "")), kind, str(d.get("source", "")),
                   dict(d.get("attributes", {})), int(rw), int(rh),
                   bool(d.get("loop", True)), float(d.get("speed", 1.0)))


class Shape(str, Enum):
    QUAD = "quad"          # 4 corners, projective or affine texture mapping
    TRIANGLE = "triangle"  # 3 corners, affine
    CIRCLE = "circle"      # 4 corners, the inscribed ellipse is shown
    MASK = "mask"          # N-point polygon drawn in black ("black hole"), no media


@dataclass
class QuadSurface:
    id: int
    name: str
    corners: list[Point]                       # stage space, BL BR TR TL (3 for triangles, N for masks)
    uv_corners: list[Point] = field(default_factory=lambda: [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
    visual_id: int | None = None
    visible: bool = True
    locked: bool = False
    opacity: float = 1.0
    blend_mode: BlendMode = BlendMode.OVER
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)   # modulation colour
    perspective: bool = True                              # projective (True) or affine (False) corner pin
    soft_edge: SoftEdge = field(default_factory=SoftEdge)
    flip_h: bool = False
    flip_v: bool = False
    # Optional mesh warp: a (cols+1) x (rows+1) grid of stage-space points replacing the corner pin.
    warp_cols: int = 0
    warp_rows: int = 0
    warp_points: list[Point] = field(default_factory=list)
    warp_smooth: bool = False                  # Catmull-Rom tessellation between the grid nodes
    shape: Shape = Shape.QUAD
    # Layer mask: a polygon in surface-local coordinates (0..1 across the surface); inside is kept
    # (or removed when inverted). Feather in local units softens the edge.
    mask_points: list[Point] = field(default_factory=list)
    mask_inverted: bool = False
    mask_feather: float = 0.0
    # Surface FX: an FX folder (ISF with fxColorForPixel) and its parameter values by input name.
    fx_name: str = ""
    fx_active: bool = False
    fx_params: dict[str, Any] = field(default_factory=dict)

    def centre(self) -> Point:
        n = max(len(self.corners), 1)
        xs = [p[0] for p in self.corners]
        ys = [p[1] for p in self.corners]
        return (sum(xs) / n, sum(ys) / n)

    def bounds(self) -> tuple[float, float, float, float]:
        pts = self.warp_points if self.warp_points else self.corners
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def translated(self, dx: float, dy: float) -> "QuadSurface":
        s = replace(self)
        s.corners = [(x + dx, y + dy) for x, y in self.corners]
        s.warp_points = [(x + dx, y + dy) for x, y in self.warp_points]
        return s

    def move(self, dx: float, dy: float) -> None:
        self.corners = [(x + dx, y + dy) for x, y in self.corners]
        self.warp_points = [(x + dx, y + dy) for x, y in self.warp_points]

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id, "name": self.name,
            "corners": [list(p) for p in self.corners],
            "uv_corners": [list(p) for p in self.uv_corners],
            "visual_id": self.visual_id, "visible": self.visible, "locked": self.locked,
            "opacity": self.opacity, "blend_mode": int(self.blend_mode), "color": list(self.color),
            "perspective": self.perspective, "soft_edge": self.soft_edge.to_dict(),
            "flip_h": self.flip_h, "flip_v": self.flip_v, "shape": self.shape.value,
        }
        if self.warp_points:
            d["warp"] = {"cols": self.warp_cols, "rows": self.warp_rows, "points": [list(p) for p in self.warp_points],
                         "smooth": self.warp_smooth}
        if self.mask_points:
            d["mask"] = {"points": [list(p) for p in self.mask_points], "inverted": self.mask_inverted,
                         "feather": self.mask_feather}
        if self.fx_name:
            d["fx"] = {"name": self.fx_name, "active": self.fx_active, "params": _jsonable(self.fx_params)}
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "QuadSurface":
        try:
            shape = Shape(str(d.get("shape", "quad")))
        except ValueError as exc:
            raise ProjectError(f"surface {d.get('id')}: unknown shape {d.get('shape')!r}") from exc
        corners = [_point(p) for p in d.get("corners", [])]
        need = {Shape.QUAD: 4, Shape.CIRCLE: 4, Shape.TRIANGLE: 3}.get(shape)
        if need is not None and len(corners) != need:
            raise ProjectError(f"surface {d.get('id')}: expected {need} corners, got {len(corners)}")
        if shape == Shape.MASK and len(corners) < 3:
            raise ProjectError(f"surface {d.get('id')}: a mask needs at least 3 points")
        uvs = [_point(p) for p in d.get("uv_corners", [[0, 0], [1, 0], [1, 1], [0, 1]])]
        if len(uvs) not in (3, 4):
            raise ProjectError(f"surface {d.get('id')}: expected 3 or 4 uv corners")
        try:
            blend = BlendMode(int(d.get("blend_mode", 2)))
        except ValueError as exc:
            raise ProjectError(f"surface {d.get('id')}: bad blend mode") from exc
        color = d.get("color", [1, 1, 1])
        s = cls(int(d["id"]), str(d.get("name", "")), corners, uvs,
                d.get("visual_id"), bool(d.get("visible", True)), bool(d.get("locked", False)),
                float(d.get("opacity", 1.0)), blend, (float(color[0]), float(color[1]), float(color[2])),
                bool(d.get("perspective", True)), SoftEdge.from_dict(d.get("soft_edge", {})),
                bool(d.get("flip_h", False)), bool(d.get("flip_v", False)))
        s.shape = shape
        warp = d.get("warp")
        if warp:
            s.warp_cols, s.warp_rows = int(warp["cols"]), int(warp["rows"])
            s.warp_points = [_point(p) for p in warp["points"]]
            s.warp_smooth = bool(warp.get("smooth", False))
            if len(s.warp_points) != (s.warp_cols + 1) * (s.warp_rows + 1):
                raise ProjectError(f"surface {s.id}: warp grid size mismatch")
        mask = d.get("mask")
        if mask:
            s.mask_points = [_point(p) for p in mask.get("points", [])]
            s.mask_inverted = bool(mask.get("inverted", False))
            s.mask_feather = float(mask.get("feather", 0.0))
        fx = d.get("fx")
        if fx:
            s.fx_name = str(fx.get("name", ""))
            s.fx_active = bool(fx.get("active", False))
            s.fx_params = dict(fx.get("params", {}))
        return s


@dataclass
class Output:
    id: int
    name: str
    centre: Point = (0.0, 0.0)
    size: tuple[float, float] = (6.4, 3.6)   # stage units
    pixel_size: tuple[int, int] = (1920, 1080)
    screen_name: str = ""                     # QScreen name to go fullscreen on ("" = none chosen)
    active: bool = True
    test_pattern: bool = False
    is_buffer: bool = False                   # a video buffer (loopback) rather than a physical output

    def rect(self) -> tuple[float, float, float, float]:
        """(left, bottom, right, top) in stage units."""
        cx, cy = self.centre
        w, h = self.size
        return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2

    def contains(self, p: Point) -> bool:
        l, b, r, t = self.rect()
        return l <= p[0] <= r and b <= p[1] <= t

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "centre": list(self.centre), "size": list(self.size),
            "pixel_size": list(self.pixel_size), "screen_name": self.screen_name, "active": self.active,
            "test_pattern": self.test_pattern, "is_buffer": self.is_buffer,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Output":
        px = d.get("pixel_size", [1920, 1080])
        return cls(int(d["id"]), str(d.get("name", "")), _point(d.get("centre", [0, 0])),
                   _point(d.get("size", [6.4, 3.6])), (int(px[0]), int(px[1])),
                   str(d.get("screen_name", "")), bool(d.get("active", True)),
                   bool(d.get("test_pattern", False)), bool(d.get("is_buffer", False)))


@dataclass
class Project:
    name: str = "Untitled"
    outputs: list[Output] = field(default_factory=list)
    surfaces: list[QuadSurface] = field(default_factory=list)   # draw order: first = bottom
    visuals: list[Visual] = field(default_factory=list)
    master_level: float = 1.0
    bpm: float = 120.0
    notes: str = ""
    osc_enabled: bool = False
    osc_port: int = 8010        # MadMapper's default input port
    osc_feedback_host: str = ""
    osc_feedback_port: int = 0
    path: str | None = None    # where it was loaded from / saved to (not serialised)

    # ---- lookups ----
    def surface(self, sid: int | None) -> QuadSurface | None:
        return next((s for s in self.surfaces if s.id == sid), None)

    def visual(self, vid: int | None) -> Visual | None:
        return next((v for v in self.visuals if v.id == vid), None)

    def output(self, oid: int | None) -> Output | None:
        return next((o for o in self.outputs if o.id == oid), None)

    def outputs_for(self, surface: QuadSurface) -> Iterator[Output]:
        l, b, r, t = surface.bounds()
        for o in self.outputs:
            ol, ob, orr, ot = o.rect()
            if r >= ol and l <= orr and t >= ob and b <= ot:
                yield o

    # ---- factories ----
    def unique_name(self, base: str, existing: list[str]) -> str:
        if base not in existing:
            return base
        for n in itertools.count(2):
            cand = f"{base}-{n}"
            if cand not in existing:
                return cand
        raise AssertionError("unreachable")

    def add_quad(self, centre: Point | None = None, size: float = 2.0, name: str = "Quad",
                 shape: "Shape" = None) -> QuadSurface:  # type: ignore[assignment]
        shape = shape or Shape.QUAD
        if centre is None:
            centre = self.outputs[0].centre if self.outputs else (0.0, 0.0)
        cx, cy = centre
        h = size / 2
        if shape == Shape.TRIANGLE:
            corners = [(cx - h, cy - h), (cx + h, cy - h), (cx, cy + h)]
            uvs = [(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)]
        else:
            corners = [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)]
            uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        if name == "Quad" and shape != Shape.QUAD:
            name = shape.value.capitalize()
        q = QuadSurface(next_id(), self.unique_name(name, [s.name for s in self.surfaces]), corners, uvs)
        q.shape = shape
        if shape == Shape.MASK:
            q.perspective = False
        self.surfaces.append(q)
        return q

    def add_output(self, name: str = "Output", pixel_size: tuple[int, int] = (1920, 1080)) -> Output:
        w = 3.6 * pixel_size[0] / pixel_size[1]
        # place to the right of the current stage extent
        right = max((o.rect()[2] for o in self.outputs), default=-w / 2)
        o = Output(next_id(), self.unique_name(name, [o.name for o in self.outputs]),
                   (right + w / 2, 0.0), (w, 3.6), pixel_size)
        self.outputs.append(o)
        return o

    def add_visual(self, kind: VisualKind, name: str, source: str = "", **attrs: Any) -> Visual:
        v = Visual(next_id(), self.unique_name(name, [v.name for v in self.visuals]), kind, source, dict(attrs))
        self.visuals.append(v)
        return v

    def remove_surface(self, sid: int) -> None:
        self.surfaces = [s for s in self.surfaces if s.id != sid]

    def remove_visual(self, vid: int) -> None:
        self.visuals = [v for v in self.visuals if v.id != vid]
        for s in self.surfaces:
            if s.visual_id == vid:
                s.visual_id = None

    def remove_output(self, oid: int) -> None:
        self.outputs = [o for o in self.outputs if o.id != oid]

    def stage_bounds(self) -> tuple[float, float, float, float]:
        """Bounding box of all outputs and surfaces (left, bottom, right, top)."""
        boxes = [o.rect() for o in self.outputs] + [s.bounds() for s in self.surfaces]
        if not boxes:
            return -3.2, -1.8, 3.2, 1.8
        return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))

    def max_id(self) -> int:
        ids = [o.id for o in self.outputs] + [s.id for s in self.surfaces] + [v.id for v in self.visuals]
        return max(ids, default=0)

    # ---- (de)serialisation ----
    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "mapstudio-project", "version": 1,
            "name": self.name, "master_level": self.master_level, "bpm": self.bpm, "notes": self.notes,
            "osc": {"enabled": self.osc_enabled, "port": self.osc_port,
                    "feedback_host": self.osc_feedback_host, "feedback_port": self.osc_feedback_port},
            "outputs": [o.to_dict() for o in self.outputs],
            "surfaces": [s.to_dict() for s in self.surfaces],
            "visuals": [v.to_dict() for v in self.visuals],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Project":
        if d.get("format") != "mapstudio-project":
            raise ProjectError("not a MapStudio project file")
        if int(d.get("version", 0)) > 1:
            raise ProjectError(f"project version {d.get('version')} is newer than this MapStudio")
        p = cls(str(d.get("name", "Untitled")),
                [Output.from_dict(o) for o in d.get("outputs", [])],
                [QuadSurface.from_dict(s) for s in d.get("surfaces", [])],
                [Visual.from_dict(v) for v in d.get("visuals", [])],
                float(d.get("master_level", 1.0)), float(d.get("bpm", 120.0)), str(d.get("notes", "")))
        osc = d.get("osc") or {}
        p.osc_enabled = bool(osc.get("enabled", False))
        p.osc_port = int(osc.get("port", 8010))
        p.osc_feedback_host = str(osc.get("feedback_host", ""))
        p.osc_feedback_port = int(osc.get("feedback_port", 0))
        reserve_ids(p.max_id())
        return p


def new_default_project() -> Project:
    p = Project()
    p.add_output("Output-1")
    tc = p.add_visual(VisualKind.TEST_CARD, "Test Card")
    q = p.add_quad(size=2.4)
    q.visual_id = tc.id
    return p


# ---- helpers --------------------------------------------------------------------------------

def _point(v: Any) -> Point:
    try:
        x, y = float(v[0]), float(v[1])
    except (TypeError, ValueError, IndexError) as exc:
        raise ProjectError(f"bad point {v!r}") from exc
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ProjectError(f"non-finite point {v!r}")
    return (x, y)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    return str(value)
