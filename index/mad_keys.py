"""Dump the header and UTF-16 key names found in a .mad project file.

Usage: python -I mad_keys.py <file.mad>
"""
import re
import struct
import sys

data = open(sys.argv[1], "rb").read()
print("size", len(data))
print("magic", data[:4].hex())
# The first words after the magic are big-endian; print the first 12 as both BE and LE.
for i in range(4, 52, 4):
    be = struct.unpack(">I", data[i:i+4])[0]
    le = struct.unpack("<I", data[i:i+4])[0]
    print(f"  off {i:3d}: BE={be:<12d} LE={le}")

# UTF-16LE identifiers (camelCase, 4+ chars)
rx = re.compile(rb"(?:[A-Za-z0-9_ .:/\-]\x00){4,}")
keys = []
seen = set()
for m in rx.finditer(data):
    s = m.group().decode("utf-16le")
    if s not in seen:
        seen.add(s)
        keys.append(s)
print(f"\nunique utf16 strings: {len(keys)}")
for k in keys[:400]:
    print("  " + k)
if len(keys) > 400:
    print(f"  ... (+{len(keys)-400} more)")

# Also ASCII strings (6+) to see whether any JSON/XML lives inside.
arx = re.compile(rb"[\x20-\x7e]{6,}")
asc = list(dict.fromkeys(m.group().decode() for m in arx.finditer(data)))
print(f"\nascii strings: {len(asc)}")
for s in asc[:60]:
    print("  " + s[:120])
