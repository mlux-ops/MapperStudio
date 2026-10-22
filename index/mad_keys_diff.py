"""Compare the UTF-16 key sets of several .mad project files.

Usage: python -I mad_keys_diff.py <base.mad> <other.mad> [<other.mad> ...]
Prints, for each 'other', the keys that do not occur in 'base' (and in no earlier 'other').
"""
import re
import sys

rx = re.compile(rb"(?:[A-Za-z0-9_ .:/\-]\x00){4,}")


def keys(path):
    data = open(path, "rb").read()
    out = []
    seen = set()
    for m in rx.finditer(data):
        s = m.group().decode("utf-16le").strip()
        # drop the leading length-byte artefact some keys carry (e.g. '0collapsed...')
        s = re.sub(r"^[0-9A-Z:.<>/]?(?=[a-zA-Z/])", "", s) if len(s) > 1 and not s[0].isalpha() and not s.startswith("/") else s
        if s and s not in seen and not re.fullmatch(r"[0-9]+", s):
            seen.add(s)
            out.append(s)
    return out


base = set(keys(sys.argv[1]))
print(f"base {sys.argv[1]}: {len(base)} keys")
known = set(base)
for p in sys.argv[2:]:
    ks = keys(p)
    new = [k for k in ks if k not in known]
    known.update(new)
    print(f"\n=== {p}: {len(ks)} keys, {len(new)} new ===")
    for k in new:
        print("  " + k)
