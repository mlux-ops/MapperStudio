"""Parse a .mad file with the pure-Python reader and print its structure.

Usage: python -I tools/mad_probe.py <file.mad|folder.madproject> [key.path] [depth]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mapstudio.madfile import read_mad_file, MadFileError  # noqa: E402
from mapstudio.madfile.qvariant_stream import UserType, QColorValue, QImageValue  # noqa: E402


def describe(v, depth=0, max_depth=2):
    pad = "  " * depth
    if isinstance(v, UserType):
        return f"<{v.type_name}> " + describe(v.value, depth, max_depth)
    if isinstance(v, dict):
        if depth >= max_depth:
            return f"{{... {len(v)} keys}}"
        body = "".join(f"{pad}  {k}: {describe(x, depth + 1, max_depth)}\n" for k, x in v.items())
        return "{\n" + body + pad + "}"
    if isinstance(v, list):
        if depth >= max_depth or not v:
            return f"[... {len(v)} items]"
        body = "".join(f"{pad}  {describe(x, depth + 1, max_depth)}\n" for x in v[:8])
        more = f"{pad}  ... +{len(v) - 8}\n" if len(v) > 8 else ""
        return "[\n" + body + more + pad + "]"
    if isinstance(v, (bytes, bytearray)):
        return f"bytes[{len(v)}] {bytes(v[:16]).hex()}"
    if isinstance(v, QColorValue):
        return f"QColor{v.to_rgba_floats()}"
    if isinstance(v, QImageValue):
        return f"QImage(format={v.format}, png {len(v.data)} bytes)"
    s = repr(v)
    return s if len(s) < 100 else s[:97] + "..."


def main() -> int:
    try:
        version, root = read_mad_file(sys.argv[1])
    except MadFileError as exc:
        print("ERROR:", exc)
        return 1
    node = root
    if len(sys.argv) > 2 and sys.argv[2]:
        for part in sys.argv[2].split("."):
            node = node[int(part)] if isinstance(node, list) else node[part]
            if isinstance(node, UserType):
                node = node.value
    print(f"fileVersion {version}, {len(root)} top-level keys")
    print(describe(node, 0, int(sys.argv[3]) if len(sys.argv) > 3 else 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
