#!/usr/bin/env python3
import os
import re
import sys
from pathlib import Path

# Keys that must not appear as workflow event triggers in the `on:` block.
# For 'issues:', we check only standalone trigger usage, not 'issues: read/write/none'
# which is valid in permissions blocks.
DISALLOWED_KEYS = ["push:", "pull_request:", "schedule:", "workflow_run:", "issues:", "issue_comment:"]
ALLOWLIST = set(["ci_policies.yml"])

# Pattern for permission values that are NOT triggers.
_PERM_VALUE = re.compile(r":\s*(read|write|none)\s*$", re.IGNORECASE)


def _key_is_trigger(txt_low: str, key: str) -> bool:
    for m in re.finditer(re.escape(key), txt_low):
        line_start = txt_low.rfind("\n", 0, m.start()) + 1
        line_end = txt_low.find("\n", m.end())
        if line_end == -1:
            line_end = len(txt_low)
        line = txt_low[line_start:line_end]
        if not _PERM_VALUE.search(line):
            return True
    return False


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
            if _key_is_trigger(low, key):
                bad.append(p.as_posix() + " contains " + key.strip())
                break
    if bad:
        print("FD_POLICY_FAIL: workflow-triggers-disallowed=" + ",".join(bad))
        return 1
    print("FD_OK: workflow triggers policy")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
