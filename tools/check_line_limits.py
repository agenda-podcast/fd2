#!/usr/bin/env python3
import os
import sys

MAX_LINES = 500
TABLE_EXT = {".csv", ".tsv"}
EXEMPT_EXT = {".png", ".jpg", ".jpeg", ".gif", ".zip", ".pdf", ".ico", ".webp"}

def is_logic_file(path):
    _, ext = os.path.splitext(path.lower())
    if ext in EXEMPT_EXT:
        return False
    if ext in TABLE_EXT:
        return False
    return True

def run(root: str) -> int:
    bad = []
    for dirpath, dirnames, filenames in os.walk(root):
        if ".git" in dirnames:
            dirnames.remove(".git")
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root)
            if rel.startswith(".git" + os.sep):
                continue
            if not is_logic_file(rel):
                continue
            try:
                with open(p, "r", encoding="utf-8", errors="strict") as f:
                    n = 0
                    for _ in f:
                        n += 1
                if n > MAX_LINES:
                    bad.append(rel + ":" + str(n))
            except Exception:
                continue
    if bad:
        sys.stdout.write("FD_POLICY_FAIL: over-500-lines=" + ",".join(sorted(bad)) + "\n")
        return 1
    sys.stdout.write("FD_POLICY_OK: line-limits\n")
    return 0


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    return run(root)

if __name__ == "__main__":
    raise SystemExit(main())
