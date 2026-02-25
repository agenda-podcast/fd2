#!/usr/bin/env python3
"""Validate workflow files for known breakage patterns.

This does not parse YAML (no deps). It enforces deterministic guards:
- no tabs
- no regex replacement artifacts like '\1'
- required file exists: .github/workflows/agent_run.yml
- agent_run.yml contains workflow_dispatch, jobs, steps
- workflow_dispatch inputs include 'type: string'
- no heredoc blocks in YAML (python - <<PY), which tend to break indentation

Exit code 2 on failure.

ASCII-only.
"""

from __future__ import annotations

import os
import sys


def fail(msg: str) -> None:
    print("[fd][wfcheck] FAIL: " + msg)
    raise SystemExit(2)


def read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def main() -> int:
    path = ".github/workflows/agent_run.yml"
    if not os.path.exists(path):
        fail("missing " + path)

    txt = read(path)
    try:
        txt.encode("ascii")
    except UnicodeEncodeError:
        fail("non-ascii in " + path)

    if "\t" in txt:
        fail("tab character found in " + path)
    if "\\1" in txt:
        fail("regex artifact \\1 found in " + path)
    if "python - <<PY" in txt or "python - <<'PY'" in txt:
        fail("heredoc in " + path + " is prohibited")

    # minimal structure checks
    for must in ["workflow_dispatch:", "jobs:", "steps:"]:
        if must not in txt:
            fail("missing required key: " + must)

    # input types
    required_inputs = ["pipeline_id:", "work_item:", "role:", "task:", "next_role:", "next_task:"]
    for k in required_inputs:
        if k not in txt:
            fail("missing input " + k)
    if "type: string" not in txt:
        fail("missing type: string in workflow_dispatch inputs")

    print("[fd][wfcheck] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
