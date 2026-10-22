"""Compile every material under the given roots in a real OpenGL context and report shader errors.

Usage: python -I tools/gl_check.py <folder> [<folder> ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext, QSurfaceFormat  # noqa: E402

from mapstudio.isf import load_material, IsfError  # noqa: E402
from mapstudio.isf.inputs import InputError  # noqa: E402
from mapstudio.render.gl import build_program, ShaderError  # noqa: E402


def main() -> int:
    fmt = QSurfaceFormat()
    fmt.setVersion(4, 1)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QGuiApplication(sys.argv[:1])
    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    assert ctx.create(), "no GL context"
    surf = QOffscreenSurface()
    surf.setFormat(fmt)
    surf.create()
    assert ctx.makeCurrent(surf)
    print("GL", ctx.format().majorVersion(), ctx.format().minorVersion(), "core" if ctx.format().profile() == QSurfaceFormat.OpenGLContextProfile.CoreProfile else "compat")
    ok = bad = 0
    for root in sys.argv[1:]:
        for folder in sorted(Path(root).iterdir()):
            if not folder.is_dir() or not any(folder.glob("*.fs")):
                continue
            try:
                m = load_material(folder)
                prog = m.assemble()
                build_program(prog.vertex, prog.fragment)
                ok += 1
                print(f"OK   {folder.name}")
            except (IsfError, InputError, OSError) as exc:
                bad += 1
                print(f"FAIL {folder.name}: parse: {exc}")
            except ShaderError as exc:
                bad += 1
                msg = str(exc).strip().replace("\n", "\n      ")
                print(f"FAIL {folder.name}: {msg[:900]}")
    print(f"\n{ok} compiled, {bad} failed")
    ctx.doneCurrent()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
