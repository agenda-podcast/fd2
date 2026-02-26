#!/usr/bin/env python3
import os
import sys

def run(repo_root: str) -> int:
    wf_dir = os.path.join(repo_root, ".github", "workflows")
    if not os.path.isdir(wf_dir):
        sys.stdout.write("FD_POLICY_FAIL: missing .github/workflows (workflows will not be visible in Actions)\n")
        return 1
    must = os.path.join(wf_dir, "ci_policies.yml")
    if not os.path.isfile(must):
        sys.stdout.write("FD_POLICY_FAIL: missing .github/workflows/ci_policies.yml\n")
        return 1
    return 0

def main() -> int:
    root = "."
    if len(sys.argv) > 1:
        root = sys.argv[1]
    return run(os.path.abspath(root))

if __name__ == "__main__":
    raise SystemExit(main())
