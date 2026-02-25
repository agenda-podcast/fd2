#!/usr/bin/env python3
"""Parse an Issue body JSON payload for fd-agent-run (pipeline mode).

Required keys:
- pipeline_id: string
- work_item: string (WI-###)
- role: string
- task: string

Optional keys:
- next_role: string
- next_task: string
- actions: list of action objects

Writes a normalized JSON file.

ASCII-only, <= 500 lines.
"""

from __future__ import annotations

import argparse
import json
import re
from typing import Any, Dict, List


def fail(msg: str) -> None:
    print("[fd][agent] input error: " + msg)
    raise SystemExit(2)


def safe_role(s: str) -> str:
    if not re.fullmatch(r"[a-z0-9_]+", s):
        fail("invalid role: %s" % s)
    return s


def safe_pipeline_id(s: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", s):
        fail("invalid pipeline_id: %s" % s)
    return s


def safe_wi(s: str) -> str:
    if not re.fullmatch(r"WI-[0-9]{3}[A-Za-z0-9_-]*", s):
        fail("invalid work_item: %s" % s)
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--issue-number", required=True)
    ap.add_argument("--issue-body", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    body = args.issue_body.strip()
    try:
        j = json.loads(body)
    except Exception:
        fail("issue body must be JSON")

    pipeline_id = safe_pipeline_id(str(j.get("pipeline_id", "")).strip())
    wi = safe_wi(str(j.get("work_item", "")).strip())
    role = safe_role(str(j.get("role", "")).strip())
    task = str(j.get("task", "")).strip()

    if not task:
        fail("task is required")

    next_role = str(j.get("next_role", "") or "").strip()
    next_task = str(j.get("next_task", "") or "").strip()

    actions = j.get("actions", [])
    if actions is None:
        actions = []
    if not isinstance(actions, list):
        fail("actions must be a list")

    out: Dict[str, Any] = {
        "pipeline_id": pipeline_id,
        "work_item": wi,
        "role": role,
        "task": task,
        "next_role": next_role,
        "next_task": next_task,
        "actions": actions,
    }

    data = json.dumps(out, indent=2) + "\n"
    if not data.isascii():
        fail("non-ASCII characters in output JSON")

    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(data)

    print("[fd][agent] parsed ok issue=%s pipeline=%s role=%s work_item=%s" % (args.issue_number, pipeline_id, role, wi))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
