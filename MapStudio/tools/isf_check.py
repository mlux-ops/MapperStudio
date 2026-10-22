"""Parse and assemble every material folder under the given roots; report failures.

Usage: python -I tools/isf_check.py <folder> [<folder> ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mapstudio.isf import load_material, IsfError  # noqa: E402
from mapstudio.isf.inputs import InputError  # noqa: E402


def main() -> int:
    ok = bad = 0
    for root in sys.argv[1:]:
        for folder in sorted(Path(root).iterdir()):
            if not folder.is_dir():
                continue
            try:
                m = load_material(folder)
                prog = m.assemble()
                m.tick(120.0)
                ok += 1
                print(f"OK   {folder.name:34s} inputs={len(m.inputs):2d} gens={len(m.generators)} "
                      f"frag={len(prog.fragment)//1024}KB")
            except (IsfError, InputError, OSError) as exc:
                bad += 1
                print(f"FAIL {folder.name:34s} {exc}")
    print(f"\n{ok} ok, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
