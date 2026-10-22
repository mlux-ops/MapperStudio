"""Scripted exercise of the UI code paths that screenshot mode does not reach.

Usage: python -I tools/ui_exercise.py [project]
Opens the project, builds the inspector for a surface and a material, changes parameters, runs
undo/redo, surface and output actions, adds media, opens and closes an output window, saves and
reloads. Prints "UI exercise OK" when everything ran without an exception.
"""
from __future__ import annotations

import faulthandler
import os
import sys
import tempfile
from pathlib import Path

faulthandler.enable()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from mapstudio.ui.app import configure_opengl  # noqa: E402

DEFAULT = r"E:\Games\MadMapperDemo 6.1.8\Resources\SampleProjects\Video Example.madproject"
LIBRARY_FILL = r"E:\Games\MadMapperDemo 6.1.8\Resources\Materials\Fill"


def main() -> int:
    configure_opengl()
    app = QApplication([])
    from mapstudio.ui.main_window import MainWindow
    win = MainWindow()
    win.quiet = True
    win.show()
    win.open_any(Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT))

    def ticks(n: int) -> None:
        for _ in range(n):
            win._tick()
            app.processEvents()

    ticks(10)
    p = win.project
    s = p.surfaces[-1]
    win.stage.select(s)
    app.processEvents()
    print("inspector widgets:", win.inspector.layout_.count())
    material = next((v for v in p.visuals if v.kind.value == "material"), None)
    if material is not None:
        win.on_visual_selected(material)
        app.processEvents()
        src = win.engine.sources[material.id]
        first = next(i for i in src.material.inputs if i.type.value == "float")
        src.set_parameter(first.name, first.max if first.max is not None else 1.0)
        print("material param set:", first.name, material.attributes[first.name])

    before = s.opacity
    s.opacity = 0.5
    win.mark_edit()
    win.undo()
    assert win.project.surface(s.id).opacity == before, "undo failed"
    win.redo()
    assert win.project.surface(s.id).opacity == 0.5, "redo failed"
    print("undo/redo ok; sources kept:", material is not None and material.id in win.engine.sources)
    ticks(3)

    win.stage.select(win.project.surfaces[-1])
    for action in ("add", "duplicate", "warp_on", "warp_reset", "warp_off", "reset", "toggle_perspective", "up", "down", "delete"):
        win.surface_action(action)
    win.stage.active_handle = 7
    win.stage.select(win.project.surfaces[0])
    win.surface_action("warp_on")
    win.stage.active_handle = 20
    win.surface_action("warp_off")
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtCore import Qt, QEvent
    win.stage.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))
    print("surface actions + stale handle ok")

    win.output_action("add")
    win.toggle_test_pattern()
    win.outputs_panel.width.setValue(1280)
    win.outputs_panel.height.setValue(720)
    print("output size applied:", win.outputs_panel.current.pixel_size, win.outputs_panel.current.size)

    win.add_media("solid", "")
    win.add_media("test_card", "")
    if Path(LIBRARY_FILL).is_dir():
        win.add_media("material", LIBRARY_FILL)
    win.assign_visual(win.project.visuals[-1])
    ticks(5)
    print("last media error:", win.engine.sources[win.project.visuals[-1].id].error)

    o = win.project.outputs[0]
    win.open_output_window(o)
    ticks(3)
    win.close_output_window(o.id)
    ticks(3)
    assert o.id not in win.output_windows, "window not removed"
    win.open_output_window(o)
    ticks(2)
    win.undo()            # restore with an open window: it must be re-pointed, not crash
    ticks(2)
    win.output_windows[o.id].close()
    ticks(3)
    print("output window open/close/undo ok")

    tmp = os.path.join(tempfile.gettempdir(), "ui_exercise.mapstudio")
    win._project_path = tmp
    win.save()
    win.open_any(Path(tmp))
    ticks(5)
    print("reloaded surfaces:", len(win.project.surfaces), "visuals:", len(win.project.visuals))
    print("status:", win.status_fps.text().strip()[:80])
    win.close()
    print("UI exercise OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
