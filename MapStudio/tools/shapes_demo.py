"""Build a demo project exercising every surface shape, layer masks, smooth warps and soft edges,
save it as a .mapstudio file and (optionally) render screenshots of it.

Usage: python -I tools/shapes_demo.py <out.mapstudio> [--screenshot DIR]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mapstudio.model import Project, VisualKind, Shape, SoftEdge, save_project  # noqa: E402
from mapstudio.render.geometry import bilinear_grid  # noqa: E402

LIBRARY = Path(r"E:\Games\MadMapperDemo 6.1.8\Resources\Materials")


def build() -> Project:
    p = Project(name="Shapes demo")
    out = p.add_output("Output-1", (1920, 1080))
    tc = p.add_visual(VisualKind.TEST_CARD, "Test Card")
    mat = p.add_visual(VisualKind.MATERIAL, "Dunes", str(LIBRARY / "Dunes")) if (LIBRARY / "Dunes").is_dir() else tc
    cx, cy = out.centre
    # quad with a feathered layer mask (hole)
    q = p.add_quad((cx - 2.0, cy + 0.8), 1.6, name="Masked quad")
    q.visual_id = tc.id
    q.mask_points = [(0.5, 0.05), (0.95, 0.5), (0.5, 0.95), (0.05, 0.5)]
    q.mask_feather = 0.05
    # circle
    c = p.add_quad((cx, cy + 0.8), 1.6, shape=Shape.CIRCLE)
    c.visual_id = mat.id
    # triangle
    t = p.add_quad((cx + 2.0, cy + 0.8), 1.6, shape=Shape.TRIANGLE)
    t.visual_id = tc.id
    # smooth-warped quad with soft edges
    w = p.add_quad((cx - 1.2, cy - 1.0), 1.8, name="Smooth warp")
    w.visual_id = mat.id
    w.warp_cols = w.warp_rows = 3
    w.warp_points = bilinear_grid(w.corners, 3, 3)
    w.warp_points[5] = (w.warp_points[5][0] + 0.35, w.warp_points[5][1] + 0.25)
    w.warp_points[10] = (w.warp_points[10][0] - 0.3, w.warp_points[10][1] - 0.2)
    w.warp_smooth = True
    w.soft_edge = SoftEdge(True, 0.3, 0.3, 0.0, 0.0)
    # mask surface (black polygon) over a quad
    q2 = p.add_quad((cx + 1.4, cy - 1.0), 1.8, name="Under mask")
    q2.visual_id = mat.id
    m = p.add_quad((cx + 1.4, cy - 1.0), 1.0, shape=Shape.MASK)
    m.corners = [(cx + 0.9, cy - 1.5), (cx + 1.9, cy - 1.4), (cx + 1.8, cy - 0.6), (cx + 1.4, cy - 0.9), (cx + 1.0, cy - 0.5)]
    return p


def main() -> int:
    out = Path(sys.argv[1])
    save_project(build(), out)
    print("saved", out)
    if "--screenshot" in sys.argv:
        d = sys.argv[sys.argv.index("--screenshot") + 1]
        subprocess.run([sys.executable, "-m", "mapstudio", str(out), "--screenshot", d, "--frames", "60"],
                       cwd=str(Path(__file__).resolve().parents[1]), check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
