"""Compile every Surface FX folder under the given roots (for quad, triangle and circle surfaces)
in a real OpenGL context and report shader errors.

Usage: python -I tools/fx_check.py <folder> [<folder> ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext, QSurfaceFormat  # noqa: E402

from mapstudio.isf import IsfError  # noqa: E402
from mapstudio.isf.fx import load_fx  # noqa: E402
from mapstudio.isf.inputs import InputError  # noqa: E402
from mapstudio.render.fx import build_fx_program  # noqa: E402
from mapstudio.render.gl import ShaderError  # noqa: E402


def main() -> int:
    fmt = QSurfaceFormat()
    fmt.setVersion(4, 1)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QGuiApplication(sys.argv[:1])
    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    assert ctx.create()
    surf = QOffscreenSurface()
    surf.setFormat(fmt)
    surf.create()
    assert ctx.makeCurrent(surf)
    ok = bad = 0
    for root in sys.argv[1:]:
        for folder in sorted(Path(root).iterdir()):
            if not folder.is_dir() or not any(folder.glob("*.vs")):
                continue
            try:
                m = load_fx(folder)
                for kind in ("quad", "triangle", "circle"):
                    m.surface_kind = kind
                    prog = m.assemble()
                    build_fx_program(prog.vertex, prog.fragment)
                m.tick(120.0)
                ok += 1
                print(f"OK   {folder.name}")
            except (IsfError, InputError, OSError) as exc:
                bad += 1
                print(f"FAIL {folder.name}: parse: {exc}")
            except ShaderError as exc:
                bad += 1
                msg = str(exc).strip().replace("\n", "\n      ")
                print(f"FAIL {folder.name}: {msg[:700]}")
    print(f"\n{ok} compiled, {bad} failed")
    ctx.doneCurrent()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
