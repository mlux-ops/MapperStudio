"""Application entry point.

    python -m mapstudio [project.mapstudio | folder.madproject] [--screenshot DIR] [--frames N]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QSurfaceFormat
from PyQt6.QtWidgets import QApplication


def configure_opengl() -> None:
    fmt = QSurfaceFormat()
    fmt.setVersion(4, 1)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    # No per-widget vsync: each QOpenGLWidget would otherwise block one display interval per paint
    # (two views = half the frame rate). The top-level window still presents once per frame.
    fmt.setSwapInterval(0)
    fmt.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mapstudio", description="MapStudio projection mapping")
    parser.add_argument("project", nargs="?", help=".mapstudio file or MadMapper .madproject folder")
    parser.add_argument("--screenshot", metavar="DIR", help="render a few frames, save PNGs of all views to DIR and quit")
    parser.add_argument("--frames", type=int, default=30, help="frames to render before the screenshot")
    args = parser.parse_args(argv)

    configure_opengl()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("MapStudio")
    app.setOrganizationName("MadMapperStudy")

    from .main_window import MainWindow   # imported after the GL format is set
    win = MainWindow()
    win.quiet = bool(args.screenshot)
    win.show()
    if args.project:
        win.open_any(Path(args.project))
    if args.screenshot:
        out = Path(args.screenshot)
        out.mkdir(parents=True, exist_ok=True)

        def select_first() -> None:
            # exercise the selection path (input view, surfaces list, inspector with material widgets)
            if win.project.surfaces:
                win.stage.select(win.project.surfaces[-1])

        def shoot() -> None:
            win.save_screenshots(out)
            win.grab().save(str(out / "window.png"))
            app.quit()
        QTimer.singleShot(int(args.frames * 1000 / 60 / 2) + 200, select_first)
        QTimer.singleShot(int(args.frames * 1000 / 60) + 500, shoot)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
