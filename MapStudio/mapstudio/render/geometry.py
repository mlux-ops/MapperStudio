"""2D geometry helpers: homographies for corner pinning, hit tests, mesh-warp grids."""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np

Point = tuple[float, float]


def homography_unit_square_to_quad(quad: Sequence[Point]) -> np.ndarray:
    """3x3 matrix H with H * (u, v, 1) ~ (x, y, w) mapping the unit square to `quad`.

    Corner order: (0,0) -> quad[0], (1,0) -> quad[1], (1,1) -> quad[2], (0,1) -> quad[3].
    Uses the classic 8-parameter solution (Heckbert).
    """
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = quad
    dx1, dy1 = x1 - x2, y1 - y2
    dx2, dy2 = x3 - x2, y3 - y2
    sx = x0 - x1 + x2 - x3
    sy = y0 - y1 + y2 - y3
    den = dx1 * dy2 - dx2 * dy1
    if abs(den) < 1e-12:   # degenerate: fall back to affine
        g = h = 0.0
    else:
        g = (sx * dy2 - dx2 * sy) / den
        h = (dx1 * sy - sx * dy1) / den
    a = x1 - x0 + g * x1
    b = x3 - x0 + h * x3
    c = x0
    d = y1 - y0 + g * y1
    e = y3 - y0 + h * y3
    f = y0
    return np.array([[a, b, c], [d, e, f], [g, h, 1.0]], dtype=np.float64)


def projective_texcoords(quad: Sequence[Point], uvs: Sequence[Point]) -> list[tuple[float, float, float]]:
    """Per-corner (u*q, v*q, q) so that linear interpolation on the GPU yields the projective map.

    `uvs` are the texture coordinates at each corner.  q is the homogeneous weight of the inverse
    homography (unit square -> quad) evaluated at the corner, which makes the two triangles of the
    quad agree on the interpolation.
    """
    h = homography_unit_square_to_quad(quad)
    out: list[tuple[float, float, float]] = []
    for (u, v), (tu, tv) in zip(((0, 0), (1, 0), (1, 1), (0, 1)), uvs):
        w = h[2, 0] * u + h[2, 1] * v + h[2, 2]
        q = 1.0 / w if abs(w) > 1e-12 else 1.0
        out.append((tu * q, tv * q, q))
    return out


def affine_texcoords(uvs: Sequence[Point]) -> list[tuple[float, float, float]]:
    return [(u, v, 1.0) for u, v in uvs]


def point_in_polygon(p: Point, poly: Sequence[Point]) -> bool:
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xi:
                inside = not inside
    return inside


def distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def bilinear_grid(corners: Sequence[Point], cols: int, rows: int) -> list[Point]:
    """Initial mesh-warp grid: (cols+1)*(rows+1) points by projective interpolation of the quad."""
    h = homography_unit_square_to_quad(corners)
    pts: list[Point] = []
    for j in range(rows + 1):
        v = j / rows
        for i in range(cols + 1):
            u = i / cols
            x, y, w = h @ np.array([u, v, 1.0])
            pts.append((float(x / w), float(y / w)))
    return pts


def grid_triangles(cols: int, rows: int) -> list[tuple[int, int, int]]:
    tris: list[tuple[int, int, int]] = []
    stride = cols + 1
    for j in range(rows):
        for i in range(cols):
            a = j * stride + i
            b = a + 1
            c = a + stride
            d = c + 1
            tris += [(a, b, d), (a, d, c)]
    return tris


def quad_from_grid(points: Sequence[Point], cols: int, rows: int) -> list[Point]:
    """The four outer corners of a warp grid (BL, BR, TR, TL)."""
    stride = cols + 1
    return [points[0], points[cols], points[rows * stride + cols], points[rows * stride]]


# ---- smooth (Catmull-Rom) warp grids ------------------------------------------------------------

def _catmull_rom(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    t2, t3 = t * t, t * t * t
    return (
        0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3),
        0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3),
    )


def _spline_row(points: Sequence[Point], subdiv: int) -> list[Point]:
    """Resample an open polyline through its points with a Catmull-Rom spline (`subdiv` segments per span)."""
    n = len(points)
    if n < 2:
        return list(points)
    ext = [points[0]] + list(points) + [points[-1]]   # clamped ends
    out: list[Point] = []
    for i in range(n - 1):
        p0, p1, p2, p3 = ext[i], ext[i + 1], ext[i + 2], ext[i + 3]
        for k in range(subdiv):
            out.append(_catmull_rom(p0, p1, p2, p3, k / subdiv))
    out.append(points[-1])
    return out


def smooth_grid(points: Sequence[Point], cols: int, rows: int, subdiv: int) -> tuple[list[Point], int, int]:
    """Tessellate a warp grid into a finer grid whose rows and columns follow Catmull-Rom splines
    through the control nodes. Returns (points, fine_cols, fine_rows)."""
    stride = cols + 1
    row_curves = [_spline_row([points[j * stride + i] for i in range(cols + 1)], subdiv) for j in range(rows + 1)]
    fine_cols = cols * subdiv
    fine_rows = rows * subdiv
    columns = [_spline_row([row_curves[j][i] for j in range(rows + 1)], subdiv) for i in range(fine_cols + 1)]
    out: list[Point] = []
    for j in range(fine_rows + 1):
        for i in range(fine_cols + 1):
            out.append(columns[i][j])
    return out, fine_cols, fine_rows


# ---- polygon triangulation (ear clipping) ----------------------------------------------------------

def signed_area(poly: Sequence[Point]) -> float:
    a = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        a += x1 * y2 - x2 * y1
    return a / 2.0


def _point_in_triangle(p: Point, a: Point, b: Point, c: Point) -> bool:
    def cross(o: Point, u: Point, v: Point) -> float:
        return (u[0] - o[0]) * (v[1] - o[1]) - (u[1] - o[1]) * (v[0] - o[0])
    d1, d2, d3 = cross(a, b, p), cross(b, c, p), cross(c, a, p)
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


def triangulate_polygon(poly: Sequence[Point]) -> list[tuple[int, int, int]]:
    """Ear-clipping triangulation of a simple polygon; returns index triples into `poly`."""
    n = len(poly)
    if n < 3:
        return []
    idx = list(range(n))
    if signed_area(poly) < 0:
        idx.reverse()
    tris: list[tuple[int, int, int]] = []
    guard = 0
    while len(idx) > 3 and guard < 10 * n:
        guard += 1
        found = False
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = poly[i0], poly[i1], poly[i2]
            if (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) <= 0:
                continue  # reflex vertex
            if any(_point_in_triangle(poly[j], a, b, c) for j in idx if j not in (i0, i1, i2)):
                continue
            tris.append((i0, i1, i2))
            del idx[k]
            found = True
            break
        if not found:   # degenerate input: fan the rest
            break
    if len(idx) >= 3:
        for k in range(1, len(idx) - 1):
            tris.append((idx[0], idx[k], idx[k + 1]))
    return tris


def polygon_centroid(poly: Sequence[Point]) -> Point:
    if not poly:
        return (0.0, 0.0)
    return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))
