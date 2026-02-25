#!/usr/bin/env python3
import os
import sys

EXEMPT_EXT = {".png", ".jpg", ".jpeg", ".gif", ".zip", ".pdf", ".ico", ".webp"}
IGNORE_DIRS = {"__pycache__"}
IGNORE_EXT = {".pyc"}

def _truthy(v: str) -> bool:
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}

def is_exempt(path: str) -> bool:
    _, ext = os.path.splitext(path.lower())
    return ext in EXEMPT_EXT

def run(root: str) -> int:
    strict_pyc = _truthy(os.environ.get("FD_ASCII_STRICT_PYC", "0"))
    bad = []
    for dirpath, dirnames, filenames in os.walk(root):
        if ".git" in dirnames:
            dirnames.remove(".git")
        if not strict_pyc:
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root)
            if rel.startswith(".git" + os.sep):
                continue
            if not strict_pyc:
                _, ext = os.path.splitext(rel.lower())
                if ext in IGNORE_EXT:
                    continue
            if is_exempt(rel):
                continue
            try:
                with open(p, "rb") as f:
                    data = f.read()
                try:
                    data.decode("ascii")
                except UnicodeDecodeError:
                    bad.append(rel)
            except Exception:
                continue
    if bad:
        sys.stdout.write("FD_POLICY_FAIL: non-ascii-files=" + ",".join(sorted(bad)) + "\n")
        return 1
    sys.stdout.write("FD_POLICY_OK: ascii\n")
    return 0

def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    return run(root)

if __name__ == "__main__":
    raise SystemExit(main())
