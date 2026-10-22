"""Extract plain text from every PDF in the MadMapper Guides folder.

Usage: python -I extract_guides.py <guides_dir> <out_dir>
Writes one .txt per PDF (page breaks marked) and prints a size table.
"""
import os
import sys

from pypdf import PdfReader

src, dst = sys.argv[1], sys.argv[2]
os.makedirs(dst, exist_ok=True)
for name in sorted(os.listdir(src)):
    if not name.lower().endswith(".pdf"):
        continue
    path = os.path.join(src, name)
    try:
        reader = PdfReader(path)
        parts = []
        for i, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            parts.append(f"\n\n===== page {i} =====\n{text}")
        out = os.path.join(dst, name[:-4] + ".txt")
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write("".join(parts))
        print(f"{len(reader.pages):4d} pages {os.path.getsize(out)//1024:5d} KB  {name}")
    except Exception as exc:  # report and continue with the next guide
        print(f"FAILED {name}: {exc}")
