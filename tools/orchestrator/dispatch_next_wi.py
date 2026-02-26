#!/usr/bin/env python3
import os
import sys

sys.dont_write_bytecode = True

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.github_api import dispatch_workflow
from src.wi_queue import pick_next_wi_issue_number

def main() -> int:
    token = os.environ.get("FD_BOT_TOKEN", "")
    if token == "":
        token = os.environ.get("GITHUB_TOKEN", "")
    if token == "":
        print("FD_FAIL: missing token (FD_BOT_TOKEN or GITHUB_TOKEN)")
        return 2
    next_issue = pick_next_wi_issue_number(token, exclude=set())
    if next_issue == 0:
        print("FD_OK: no open work items")
        return 0
    dispatch_workflow("orchestrate_wi_issue.yml", "main", {"issue_number": str(next_issue), "role_guide": ""}, token)
    print("FD_OK: dispatched issue " + str(next_issue))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
