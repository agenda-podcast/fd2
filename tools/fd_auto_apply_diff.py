#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

def main() -> int:
    if len(sys.argv) < 2:
        print("usage: fd_auto_apply_diff.py <diff_file>")
        return 2
    diff_file = Path(sys.argv[1])
    if not diff_file.exists():
        print("FD_FAIL: diff file not found")
        return 2
    data = diff_file.read_text(encoding="utf-8", errors="ignore")
    if "diff --git" not in data:
        print("FD_FAIL: not a unified diff")
        return 2
    # apply in cwd repo
    r = subprocess.run(["git","apply","--whitespace=nowarn","--reject"], input=data, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(r.stdout)
    return r.returncode

if __name__ == "__main__":
    raise SystemExit(main())
