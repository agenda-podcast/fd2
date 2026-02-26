#!/usr/bin/env python3
import os
import re
import sys

EXEMPT_EXT = {".png", ".jpg", ".jpeg", ".gif", ".zip", ".pdf", ".ico", ".webp"}
IGNORE_DIRS = {".git", "__pycache__", ".pytest_cache", "agent_guides"}
IGNORE_FILES = {"tools/check_no_placeholders.py"}

BANNED_PATTERNS = [
    r"__REPLACE_ME__",
    r"__APP_REPO_URL__",
    r"__APP_REPO_DIRECTORY__",
    r"example\.com",
    r"\bTODO\b",
    r"\bFIXME\b",
    r"\bplaceholder\b",
    r"\bsimulat(e|ed|ion)\b",
    r"\bmock\b",
    r"\[Specify",
    r"\[Link to",
]

def is_exempt(path: str) -> bool:
    _, ext = os.path.splitext(path.lower())
    return ext in EXEMPT_EXT

def run(root: str) -> int:
    bad = []
    rx = [re.compile(p, re.IGNORECASE) for p in BANNED_PATTERNS]
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root)
            if rel.startswith(".git" + os.sep):
                continue
            if rel.replace(os.sep, "/") in IGNORE_FILES:
                continue
            if is_exempt(rel):
                continue
            try:
                txt = open(p, "r", encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            for r in rx:
                m = r.search(txt)
                if m:
                    bad.append(rel + ":" + r.pattern)
                    break
    if bad:
        sys.stdout.write("FD_POLICY_FAIL: placeholders-or-skeletons=" + ",".join(sorted(bad)) + "\n")
        return 1
    sys.stdout.write("FD_POLICY_OK: no-placeholders\n")
    return 0

def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    return run(root)

if __name__ == "__main__":
    raise SystemExit(main())
