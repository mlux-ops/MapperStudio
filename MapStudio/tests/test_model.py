"""Tests for the project model, JSON persistence, geometry and the MadMapper importer."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mapstudio.model import Project, QuadSurface, Output, Visual, VisualKind, BlendMode, SoftEdge, ProjectError
from mapstudio.model import new_default_project, save_project, load_project
from mapstudio.model.mad_import import import_mad_project
from mapstudio.render.geometry import homography_unit_square_to_quad, projective_texcoords, point_in_polygon, bilinear_grid

SAMPLES = Path(r"E:\Games\MadMapperDemo 6.1.8\Resources\SampleProjects")
needs_samples = pytest.mark.skipif(not SAMPLES.is_dir(), reason="MadMapper demo samples not installed")


def test_default_project_has_output_quad_and_test_card():
    p = new_default_project()
    assert len(p.outputs) == 1 and len(p.surfaces) == 1 and len(p.visuals) == 1
    assert p.surfaces[0].visual_id == p.visuals[0].id
    assert list(p.outputs_for(p.surfaces[0])) == p.outputs


def test_roundtrip_json(tmp_path: Path):
    p = new_default_project()
    q = p.surfaces[0]
    q.soft_edge = SoftEdge(True, 0.2, 0.0, 0.1, 0.0, gamma=2.2)
    q.blend_mode = BlendMode.ADD
    q.warp_cols = q.warp_rows = 2
    q.warp_points = bilinear_grid(q.corners, 2, 2)
    img = p.add_visual(VisualKind.IMAGE, "pic", str(tmp_path / "pic.png"))
    path = tmp_path / "proj.mapstudio"
    save_project(p, path)
    p2 = load_project(path)
    assert p2.surfaces[0].soft_edge == q.soft_edge
    assert p2.surfaces[0].blend_mode == BlendMode.ADD
    assert len(p2.surfaces[0].warp_points) == 9
    assert p2.visual(img.id).source == str((tmp_path / "pic.png").resolve())   # relative path restored


def test_from_dict_rejects_garbage():
    with pytest.raises(ProjectError):
        Project.from_dict({"format": "nope"})
    with pytest.raises(ProjectError):
        Project.from_dict({"format": "mapstudio-project", "version": 1, "surfaces": [{"id": 1, "corners": [[0, 0]]}]})
    with pytest.raises(ProjectError):
        Project.from_dict({"format": "mapstudio-project", "version": 99})


def test_unique_names_and_ids():
    p = Project()
    a = p.add_quad(name="Quad")
    b = p.add_quad(name="Quad")
    assert a.name == "Quad" and b.name == "Quad-2" and a.id != b.id


def test_homography_maps_unit_square_corners():
    quad = [(0.0, 0.0), (4.0, 0.5), (3.0, 3.0), (-1.0, 2.0)]
    h = homography_unit_square_to_quad(quad)
    for (u, v), (x, y) in zip([(0, 0), (1, 0), (1, 1), (0, 1)], quad):
        px, py, pw = h @ np.array([u, v, 1.0])
        assert (px / pw, py / pw) == pytest.approx((x, y))
    tcs = projective_texcoords(quad, [(0, 0), (1, 0), (1, 1), (0, 1)])
    assert all(q > 0 for _, _, q in tcs)


def test_point_in_polygon():
    sq = [(0, 0), (1, 0), (1, 1), (0, 1)]
    assert point_in_polygon((0.5, 0.5), sq)
    assert not point_in_polygon((1.5, 0.5), sq)


@needs_samples
def test_import_video_example():
    p, report = import_mad_project(SAMPLES / "Video Example.madproject")
    assert report.file_version == 18
    assert [s.name for s in p.surfaces] == ["Quad-1", "Quad-2"]   # file order reversed: MadMapper lists foreground first
    assert all(s.perspective for s in p.surfaces)
    dunes = next(v for v in p.visuals if v.name == "Dunes")
    assert dunes.kind == VisualKind.MATERIAL and Path(dunes.source).is_dir()
    assert dunes.attributes.get("__by_label__") is True
    movie = next(v for v in p.visuals if v.kind == VisualKind.MOVIE)
    assert Path(movie.source).exists()
    assert p.outputs[0].pixel_size == (1440, 900)
    assert p.surfaces[0].visual_id == dunes.id


@needs_samples
def test_import_softedge_example_links_loopback_and_softedges():
    p, report = import_mad_project(SAMPLES / "SoftEdge Blending 2 Outputs Example.madproject")
    assert len(p.outputs) == 3
    loops = [v for v in p.visuals if v.kind == VisualKind.OUTPUT_LOOPBACK]
    assert loops and all(p.output(int(v.source)) is not None for v in loops)
    out1 = next(s for s in p.surfaces if s.name == "output1")
    assert out1.soft_edge.active and out1.soft_edge.right == pytest.approx(0.399, abs=1e-3)
    assert any("lines" in s for s in report.skipped)
