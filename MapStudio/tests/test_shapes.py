"""Tests for surface shapes, layer masks, smooth warps and the related geometry helpers."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mapstudio.model import Project, Shape, VisualKind, save_project, load_project, ProjectError
from mapstudio.render.geometry import triangulate_polygon, smooth_grid, bilinear_grid, signed_area
from mapstudio.render.engine import surface_vertices


def test_triangulation_covers_concave_polygon():
    poly = [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)]
    tris = triangulate_polygon(poly)
    assert len(tris) == len(poly) - 2
    assert sum(abs(signed_area([poly[i] for i in t])) for t in tris) == pytest.approx(3.0)
    # orientation-independent
    assert len(triangulate_polygon(list(reversed(poly)))) == 4


def test_smooth_grid_interpolates_nodes():
    corners = [(0, 0), (4, 0), (4, 3), (0, 3)]
    grid = bilinear_grid(corners, 2, 2)
    pts, c, r = smooth_grid(grid, 2, 2, 4)
    assert (c, r) == (8, 8) and len(pts) == 81
    assert pts[0] == pytest.approx((0.0, 0.0)) and pts[-1] == pytest.approx((4.0, 3.0))
    assert pts[4 * 9 + 4] == pytest.approx(grid[4])     # centre node preserved


def test_surface_vertices_per_shape():
    p = Project()
    p.add_output()
    q = p.add_quad(size=2.0)
    assert surface_vertices(q).shape == (6, 7)
    t = p.add_quad(size=2.0, shape=Shape.TRIANGLE)
    assert len(t.corners) == 3 and surface_vertices(t).shape == (3, 7)
    m = p.add_quad(size=2.0, shape=Shape.MASK)
    m.corners = [(0, 0), (1, 0), (1, 1), (0.5, 0.5), (0, 1)]
    assert surface_vertices(m).shape == (9, 7)
    q.warp_cols = q.warp_rows = 2
    q.warp_points = bilinear_grid(q.corners, 2, 2)
    q.warp_smooth = True
    v = surface_vertices(q)
    assert v.shape == (12 * 12 * 6, 7)


def test_shapes_mask_fx_roundtrip(tmp_path: Path):
    p = Project()
    p.add_output()
    c = p.add_quad(size=1.0, shape=Shape.CIRCLE)
    c.mask_points = [(0.1, 0.1), (0.9, 0.1), (0.5, 0.9)]
    c.mask_inverted = True
    c.mask_feather = 0.02
    c.fx_name = "Color Controls"
    c.fx_active = True
    c.fx_params = {"fx_brightness": 0.5}
    t = p.add_quad(size=1.0, shape=Shape.TRIANGLE)
    path = tmp_path / "s.mapstudio"
    save_project(p, path)
    p2 = load_project(path)
    c2 = p2.surface(c.id)
    assert c2.shape == Shape.CIRCLE and c2.mask_inverted and c2.mask_feather == 0.02
    assert c2.mask_points == c.mask_points and c2.fx_params == {"fx_brightness": 0.5} and c2.fx_active
    assert p2.surface(t.id).shape == Shape.TRIANGLE and len(p2.surface(t.id).corners) == 3


def test_shape_validation():
    with pytest.raises(ProjectError):
        Project.from_dict({"format": "mapstudio-project", "version": 1,
                           "surfaces": [{"id": 1, "shape": "triangle", "corners": [[0, 0], [1, 0], [1, 1], [0, 1]]}]})
    with pytest.raises(ProjectError):
        Project.from_dict({"format": "mapstudio-project", "version": 1,
                           "surfaces": [{"id": 1, "shape": "blob", "corners": [[0, 0], [1, 0], [1, 1], [0, 1]]}]})
