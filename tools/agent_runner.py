#!/usr/bin/env python3
"""Deprecated wrapper.

Use tools/agent_pipeline.py (deterministic, no LLM) instead.

This wrapper accepts the old flags and produces an equivalent payload with no actions.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--work_item", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pipeline_id", default="P-local-0001")
    args = ap.parse_args()

    payload = {
        "pipeline_id": args.pipeline_id,
        "work_item": args.work_item,
        "role": args.role,
        "task": args.task,
        "next_role": "",
        "next_task": "",
        "actions": [],
    }
    os.makedirs("tools", exist_ok=True)
    with open("tools/_runner_input.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(payload, indent=2) + "\n")

    cmd = [sys.executable, "tools/agent_pipeline.py", "--input", "tools/_runner_input.json", "--out", args.out]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
