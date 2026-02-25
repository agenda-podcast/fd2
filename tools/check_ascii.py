#!/usr/bin/env python3
"""Fail CI if prohibited non-ASCII appears in checked files.

Policy:
- By default, all tracked .md/.html/.css/.js/.py/.yml/.yaml/.json/.txt are checked.
- An allowlist file can exempt specific paths from ASCII enforcement.

Exit codes:
- 0: pass
- 1: fail
"""

from __future__ import annotations

import os
import sys
import subprocess
from typing import List, Set


DEFAULT_EXTS = {".md", ".html", ".css", ".js", ".py", ".yml", ".yaml", ".json", ".txt"}
ALLOWLIST_PATH = "tools/ascii_allowlist.txt"


def git_ls_files() -> List[str]:
    p = subprocess.run(["git", "ls-files"], check=True, capture_output=True, text=True)
    return [line.strip() for line in p.stdout.splitlines() if line.strip()]


def read_allowlist() -> Set[str]:
    if not os.path.exists(ALLOWLIST_PATH):
        return set()
    out: Set[str] = set()
    with open(ALLOWLIST_PATH, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            out.add(s)
    return out


def is_checked(path: str) -> bool:
    _, ext = os.path.splitext(path)
    if ext.lower() not in DEFAULT_EXTS:
        return False
    if path.startswith("evidence/"):
        return False
    return True


def has_non_ascii_bytes(data: bytes) -> bool:
    try:
        data.decode("ascii")
        return False
    except UnicodeDecodeError:
        return True


def main() -> int:
    allow = read_allowlist()
    files = [p for p in git_ls_files() if is_checked(p) and p not in allow]

    bad: List[str] = []
    for path in files:
        with open(path, "rb") as f:
            data = f.read()
        if has_non_ascii_bytes(data):
            bad.append(path)

    if bad:
        print("[fd][policy] ASCII-only check FAILED. Non-ASCII detected in:")
        for p in bad:
            print(" - " + p)
        print("[fd][policy] Fix: replace non-ASCII characters or add a path to tools/ascii_allowlist.txt")
        return 1

    print("[fd][policy] ASCII-only check PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
