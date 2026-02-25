#!/usr/bin/env python3
import os
import sys

EXEMPT_EXT = {".png", ".jpg", ".jpeg", ".gif", ".zip", ".pdf", ".ico", ".webp"}

def is_exempt(path):
    _, ext = os.path.splitext(path.lower())
    return ext in EXEMPT_EXT

def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    bad = []
    for dirpath, dirnames, filenames in os.walk(root):
        if ".git" in dirnames:
            dirnames.remove(".git")
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root)
            if rel.startswith(".git" + os.sep):
                continue
            if is_exempt(rel):
                continue
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read()
                if "..." in txt:
                    bad.append(rel)
            except Exception:
                continue
    if bad:
        sys.stdout.write("FD_POLICY_FAIL: ellipses-found=" + ",".join(sorted(bad)) + "\n")
        return 1
    sys.stdout.write("FD_POLICY_OK: no-ellipses\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
