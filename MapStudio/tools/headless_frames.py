"""Load a project headlessly, render N engine frames and one image per output; print errors.

Usage: python -X faulthandler -I tools/headless_frames.py <project> [frames] [outdir]
"""
from __future__ import annotations

import faulthandler
import sys
import time
from pathlib import Path

faulthandler.enable()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402
from PyQt6.QtGui import QGuiApplication, QSurfaceFormat  # noqa: E402

from mapstudio.model import load_project  # noqa: E402
from mapstudio.model.mad_import import import_mad_project  # noqa: E402
from mapstudio.render import RenderEngine, ViewRect  # noqa: E402
from mapstudio.render.gl import make_fbo  # noqa: E402


def main() -> int:
    fmt = QSurfaceFormat()
    fmt.setVersion(4, 1)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QGuiApplication(sys.argv[:1])
    path = Path(sys.argv[1])
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    outdir = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    if path.suffix.lower() == ".mapstudio":
        project = load_project(path)
    else:
        project, report = import_mad_project(path)
        print(report.summary(), file=sys.stderr)
    engine = RenderEngine(project)
    t0 = time.perf_counter()
    for i in range(frames):
        assert engine.make_current()
        print(f"frame {i}", file=sys.stderr, flush=True)
        engine.frame()
        engine.done_current()
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        time.sleep(1 / 60)
    dt = time.perf_counter() - t0
    print(f"{frames} frames in {dt:.2f}s", file=sys.stderr)
    for v in project.visuals:
        src = engine.sources.get(v.id)
        print(f"{v.name:30s} {v.kind.value:16s} tex={bool(src and src.texture())} err={src.error if src else 'no source'}", file=sys.stderr)
    if outdir:
        outdir.mkdir(parents=True, exist_ok=True)
        assert engine.make_current()
        for o in project.outputs:
            fbo = make_fbo(*o.pixel_size)
            fbo.bind()
            engine.draw_stage(ViewRect.for_output(o), o.pixel_size, outputs=[o], clip_to_outputs=True)
            fbo.release()
            fbo.toImage().save(str(outdir / f"output-{o.id}.png"))
        engine.done_current()
        print("saved", outdir, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
