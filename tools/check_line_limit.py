#!/usr/bin/env python3
"""Fail CI if any non-table logic/code file exceeds the max line limit.

FD policy:
- Max lines per non-table logic/code file: 500
- "Table" files are exempt (CSV/TSV) and evidence files are exempt.
- Checked extensions: .py .js .ts .html .css .yml .yaml .json .md .txt
- Optional allowlist to exempt specific paths.

Exit codes:
- 0: pass
- 1: fail
"""

from __future__ import annotations

import os
import sys
import subprocess
from typing import List, Set, Tuple


MAX_LINES = 500
CHECK_EXTS = {".py", ".js", ".ts", ".html", ".css", ".yml", ".yaml", ".json", ".md", ".txt"}
TABLE_EXTS = {".csv", ".tsv"}
ALLOWLIST_PATH = "tools/line_limit_allowlist.txt"


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
    if path.startswith("evidence/"):
        return False
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    if ext in TABLE_EXTS:
        return False
    return ext in CHECK_EXTS


def count_lines(path: str) -> int:
    with open(path, "r", encoding="utf-8", newline="") as f:
        return sum(1 for _ in f)


def main() -> int:
    allow = read_allowlist()
    files = [p for p in git_ls_files() if is_checked(p) and p not in allow]

    over: List[Tuple[str, int]] = []
    for path in files:
        n = count_lines(path)
        if n > MAX_LINES:
            over.append((path, n))

    if over:
        print("[fd][policy] Line limit check FAILED. Max lines: %d" % MAX_LINES)
        for path, n in over:
            print(" - %s: %d lines" % (path, n))
        print("[fd][policy] Fix: split files, or add a path to tools/line_limit_allowlist.txt")
        return 1

    print("[fd][policy] Line limit check PASS (max %d)" % MAX_LINES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
