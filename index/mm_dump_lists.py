"""Write full category lists from mm_strings.txt to separate text files.

Usage: python -I mm_dump_lists.py <strings.txt> <outdir>
"""
import os
import re
import sys
from collections import OrderedDict

src, outdir = sys.argv[1], sys.argv[2]
lines = [ln.rstrip("\n")[2:] for ln in open(src, encoding="utf-8")]
uniq = list(OrderedDict.fromkeys(lines))

lists = OrderedDict([
    ("osc_addresses", re.compile(r"^/[a-z][a-z0-9_]*(/[A-Za-z0-9_\-\[\]\*%]+)+$")),
    ("class_names_mad", re.compile(r"^(Mad|MM)[A-Z][A-Za-z0-9]{3,}$")),
    ("cpp_scoped", re.compile(r"^[A-Za-z_][A-Za-z0-9_]*::[A-Za-z_][A-Za-z0-9_:]*$")),
    ("qt_signals_slots", re.compile(r"^[12][a-zA-Z_][A-Za-z0-9_]*\([A-Za-z0-9_:,<> *&]*\)$")),
    ("rtti_classes", re.compile(r"^\.\?AV[A-Za-z_][A-Za-z0-9_@?$]*@@$")),
    ("release_notes", re.compile(r"^\s*[-+*] |Release Notes$")),
    ("isf_glsl", re.compile(r"ISF|isf_|GENERATORS|IMPORTED|PASSES|materialColorForPixel|uniform |#version", re.I)),
    ("dmx_artnet", re.compile(r"art-?net|sACN|DMX|fixture", re.I)),
    ("ui_object_names", re.compile(r"^[a-z][A-Za-z0-9]*(Button|Widget|Dialog|SpinBox|CheckBox|ComboBox|Slider|Label|View|Panel|Editor)$")),
    ("urls", re.compile(r"^https?://")),
    ("file_patterns", re.compile(r"\(\*\.[a-z0-9]+|\.(mad|madproject|ldat|isf|fs|vs|obj|svg|ild|hap|mov|mp4|png|jpg|exr|csv|json|xml|lua|py)\b", re.I)),
])

os.makedirs(outdir, exist_ok=True)
for name, rx in lists.items():
    hits = [s for s in uniq if rx.search(s)]
    path = os.path.join(outdir, f"mm_{name}.txt")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(hits) + "\n")
    print(f"{name}: {len(hits)} -> {path}")
