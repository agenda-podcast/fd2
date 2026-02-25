#!/usr/bin/env python3
"""FD Agent Pipeline Runner (no LLM, deterministic).

Reads a JSON input payload (Issue body shape) and:
- loads role config
- validates allowed action types for the role
- executes actions
- writes an artifact bundle under an output folder
- creates a ZIP of that folder

This script does not create Issues or PRs; the GitHub Actions workflow does that.

ASCII-only, <= 500 lines.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import zipfile
from typing import Any, Dict, List

from actions import run_actions, ensure_ascii


ROLE_DIR = "agents/roles"


def safe_role(s: str) -> str:
    if not re.fullmatch(r"[a-z0-9_]+", s):
        raise ValueError("Invalid role: %s" % s)
    return s


def safe_pipeline_id(s: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", s):
        raise ValueError("Invalid pipeline_id: %s" % s)
    return s


def safe_work_item(s: str) -> str:
    if not re.fullmatch(r"WI-[0-9]{3}[A-Za-z0-9_-]*", s):
        raise ValueError("Invalid work_item: %s" % s)
    return s


def read_role_config(role: str) -> Dict[str, Any]:
    path = os.path.join(ROLE_DIR, role + ".json")
    if not os.path.exists(path):
        raise FileNotFoundError("Role config not found: %s" % path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def zip_dir(src_dir: str, zip_path: str) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for dirpath, _, filenames in os.walk(src_dir):
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, src_dir)
                z.write(full, arcname=rel)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="path to issue JSON payload")
    ap.add_argument("--out", required=True, help="output folder for this agent run")
    args = ap.parse_args()

    payload = json.load(open(args.input, "r", encoding="utf-8"))

    pipeline_id = safe_pipeline_id(str(payload.get("pipeline_id", "")).strip())
    work_item = safe_work_item(str(payload.get("work_item", "")).strip())
    role = safe_role(str(payload.get("role", "")).strip())
    task = str(payload.get("task", "")).strip()

    actions = payload.get("actions", [])
    if not isinstance(actions, list):
        raise ValueError("actions must be a list")

    role_cfg = read_role_config(role)
    allowed = role_cfg.get("allowed_actions", [])
    if not isinstance(allowed, list):
        allowed = []

    for a in actions:
        t = str(a.get("type", "")).strip()
        if allowed and t not in allowed:
            raise ValueError("Action type not allowed for role=%s: %s" % (role, t))

    os.makedirs(args.out, exist_ok=True)

    res = run_actions(actions)

    meta = {
        "pipeline_id": pipeline_id,
        "work_item": work_item,
        "role": role,
        "task": task,
        "changed_paths": res.changed_paths,
        "notes": res.notes,
        "timestamp_utc": int(time.time()),
    }
    meta_txt = json.dumps(meta, indent=2) + "\n"
    ensure_ascii(meta_txt)

    with open(os.path.join(args.out, "AGENT_META.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(meta_txt)

    summary_lines = []
    summary_lines.append("# FD Agent Run Summary")
    summary_lines.append("")
    summary_lines.append("- Pipeline: %s" % pipeline_id)
    summary_lines.append("- Work Item: %s" % work_item)
    summary_lines.append("- Role: %s" % role)
    summary_lines.append("- Task: %s" % task)
    summary_lines.append("")
    summary_lines.append("## Changed paths")
    if res.changed_paths:
        for p in res.changed_paths:
            summary_lines.append("- %s" % p)
    else:
        summary_lines.append("- (none)")
    summary_lines.append("")
    summary_lines.append("## Notes")
    for n in res.notes:
        summary_lines.append("- %s" % n)
    summary = "\n".join(summary_lines) + "\n"
    ensure_ascii(summary)

    with open(os.path.join(args.out, "AGENT_OUTPUT.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(summary)

    zip_path = os.path.join(args.out, "ARTIFACTS.zip")
    zip_dir(args.out, zip_path)

    print("[fd][agent] ok pipeline=%s work_item=%s role=%s out=%s" % (pipeline_id, work_item, role, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
