"""Categorize extracted strings from mm_strings.txt and print bounded samples.

Usage: python -I mm_grep.py <strings.txt>
"""
import re
import sys
from collections import OrderedDict

lines = [ln.rstrip("\n")[2:] for ln in open(sys.argv[1], encoding="utf-8")]
uniq = list(OrderedDict.fromkeys(lines))

cats = OrderedDict([
    ("dll imports", re.compile(r"^[A-Za-z0-9_.\-]+\.dll$", re.I)),
    ("osc addresses", re.compile(r"^/[a-z][a-z0-9_]*(/[A-Za-z0-9_\-\[\]\*%]+)+$")),
    ("Mad* / MM* class names", re.compile(r"^(Mad|MM)[A-Z][A-Za-z0-9]{3,}$")),
    ("cpp scoped names", re.compile(r"^[A-Za-z_][A-Za-z0-9_]*::[A-Za-z_][A-Za-z0-9_:]*$")),
    ("file extensions", re.compile(r"^\*?\.[a-z0-9]{2,5}$", re.I)),
    ("isf/glsl", re.compile(r"ISF|materialColorForPixel|GENERATORS|IMPORTED|PASSES|isf\.video", re.I)),
    ("lua", re.compile(r"^lua[_A-Z]|LUA_|\.lua$|luaL_", re.I)),
    ("python", re.compile(r"^Py[A-Z_]|python3|PYTHONPATH|site-packages", re.I)),
    ("version/build", re.compile(r"\b6\.1\.\d+\b|MadMapper \d|Build|__DATE__|Jan|Feb|Mar \d|Compiled", re.I)),
    ("spout/syphon/ndi", re.compile(r"spout|syphon|NDI", re.I)),
    ("artnet/sacn/dmx", re.compile(r"art-?net|sACN|E1\.31|DMX", re.I)),
    ("project format", re.compile(r"madproject|\.mad\b|Auto-?Save|Resources/|Collect External|\.ldat", re.I)),
    ("surface types", re.compile(r"^(Quad|Triangle|Circle|Line|Mesh|Mask|Surface3D|Fixture|Group)[A-Za-z]*$")),
    ("shaders glsl keywords", re.compile(r"^(uniform|varying|in |out |#version|gl_FragColor|layout\()", re.I)),
    ("registry/settings", re.compile(r"HKEY_|Software\\\\|\.ini$|QSettings|AppData", re.I)),
    ("license/demo", re.compile(r"demo|licen[sc]e|watermark|authoriz", re.I)),
])

LIMIT = 40
for name, rx in cats.items():
    hits = [s for s in uniq if rx.search(s)]
    print(f"\n### {name}: {len(hits)}")
    for s in hits[:LIMIT]:
        print("  " + s[:140])
    if len(hits) > LIMIT:
        print(f"  ... (+{len(hits)-LIMIT} more)")
