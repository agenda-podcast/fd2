#!/usr/bin/env python3
"""Build next agent Issue body JSON deterministically.

Inputs:
- --issue-input: path to tools/issue_input.json
- --role: next role id
- --task: next task text
- --out: output file path

Output is strict JSON.

ASCII-only.
"""

from __future__ import annotations

import argparse
import json


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--issue-input", required=True)
    ap.add_argument("--role", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    j = json.load(open(args.issue_input, "r", encoding="utf-8"))
    out = {
        "pipeline_id": j["pipeline_id"],
        "work_item": j["work_item"],
        "role": args.role,
        "task": args.task,
        "next_role": "",
        "next_task": "",
        "actions": [],
    }

    data = json.dumps(out, indent=2) + "\n"
    data.encode("ascii")
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
