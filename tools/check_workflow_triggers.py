#!/usr/bin/env python3
import os
import sys
from pathlib import Path

DISALLOWED_KEYS = ["push:", "pull_request:", "schedule:", "workflow_run:", "issues:", "issue_comment:"]
ALLOWLIST = set(["ci_policies.yml"])

def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    wf_dir = root / ".github" / "workflows"
    if not wf_dir.exists():
        print("FD_FAIL: missing .github/workflows")
        return 2
    bad = []
    for p in wf_dir.glob("*.yml"):
        if p.name in ALLOWLIST:
            continue
        try:
            txt = p.read_text(encoding="utf-8")
        except Exception:
            continue
        low = txt.lower()
        for key in DISALLOWED_KEYS:
            if key in low:
                bad.append(p.as_posix() + " contains " + key.strip())
                break
    if bad:
        print("FD_POLICY_FAIL: workflow-triggers-disallowed=" + ",".join(bad))
        return 1
    print("FD_OK: workflow triggers policy")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
