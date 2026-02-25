#!/usr/bin/env python3
"""Determine next role/task when next_role is missing.

Input: tools/issue_input.json (produced by parser)
Output: prints JSON to stdout:
{"next_role": "...", "next_task": "..."}

Logic:
- If next_role is present and non-empty: return it (and next_task as provided).
- Else infer from role order mapping:
  pm -> tech_lead -> be -> fe -> reviewer -> qa -> (complete)

Tasks are template defaults if missing.

ASCII-only.
"""

from __future__ import annotations

import json
import sys
from typing import Dict


ROLE_CHAIN = ["pm", "tech_lead", "be", "fe", "reviewer", "qa"]

DEFAULT_TASK = {
    "tech_lead": "Define technical approach and WI decomposition",
    "be": "Implement repo tools, scripts, or backend logic per WI",
    "fe": "Implement UI changes per WI (docs/assets)",
    "reviewer": "Review changes against FD checklists; request changes or approve",
    "qa": "Verify acceptance criteria and E2E scenarios; record evidence",
}


def main() -> int:
    path = "tools/issue_input.json"
    j = json.load(open(path, "r", encoding="utf-8"))
    nr = (j.get("next_role") or "").strip()
    nt = (j.get("next_task") or "").strip()
    role = (j.get("role") or "").strip()

    if nr:
        out = {"next_role": nr, "next_task": nt}
        print(json.dumps(out))
        return 0

    if role not in ROLE_CHAIN:
        # Unknown role: default to tech_lead
        out = {"next_role": "tech_lead", "next_task": DEFAULT_TASK["tech_lead"]}
        print(json.dumps(out))
        return 0

    idx = ROLE_CHAIN.index(role)
    if idx >= len(ROLE_CHAIN) - 1:
        out = {"next_role": "", "next_task": ""}
        print(json.dumps(out))
        return 0

    inferred = ROLE_CHAIN[idx + 1]
    out = {"next_role": inferred, "next_task": DEFAULT_TASK.get(inferred, "")}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
