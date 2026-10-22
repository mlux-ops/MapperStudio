"""Extract printable ASCII and UTF-16LE strings from a binary file.

Usage: python -I mm_strings.py <input> <output> [minlen]
Writes one string per line, prefixed with 'A ' (ascii) or 'U ' (utf-16le).
"""
import re
import sys

src, dst = sys.argv[1], sys.argv[2]
minlen = int(sys.argv[3]) if len(sys.argv) > 3 else 5

data = open(src, "rb").read()
ascii_re = re.compile(rb"[\x20-\x7e]{%d,}" % minlen)
utf16_re = re.compile(rb"(?:[\x20-\x7e]\x00){%d,}" % minlen)

count_a = count_u = 0
with open(dst, "w", encoding="utf-8", newline="\n") as out:
    for m in ascii_re.finditer(data):
        out.write("A " + m.group().decode("ascii") + "\n")
        count_a += 1
    for m in utf16_re.finditer(data):
        out.write("U " + m.group().decode("utf-16le") + "\n")
        count_u += 1

print(f"{src}: {len(data)} bytes, ascii={count_a}, utf16={count_u} -> {dst}")
