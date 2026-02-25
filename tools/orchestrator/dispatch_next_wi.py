#!/usr/bin/env python3
import os
import re
import sys
from typing import Any, Dict, List, Tuple

from src.github_api import list_issues, workflow_dispatch
from src.github_api import get_issue
from src.github_api import create_comment

ROLE_TO_GUIDE = {
    "Product Manager (PM)": "ROLE_PM.txt",
    "Tech Lead (Architecture / Delivery Lead)": "ROLE_TECH_LEAD.txt",
    "Frontend Engineer (FE)": "ROLE_FE.txt",
    "Backend Engineer (BE)": "ROLE_BE.txt",
    "DevOps / Platform Engineer": "ROLE_DEVOPS.txt",
    "Code Reviewer": "ROLE_REVIEWER.txt",
    "QA Lead": "ROLE_QA.txt",
    "Release Manager": "ROLE_DEVOPS.txt",
    "Technical Writer": "ROLE_TECH_WRITER.txt",
}

def die(msg: str) -> None:
    sys.stdout.write(msg + "\n")
    raise SystemExit(1)

def _parse_task_num(title: str, body: str) -> str:
    m = re.search(r"\bTask Number:\s*([0-9]+(?:\.[0-9]+)*)\b", body)
    if m:
        return m.group(1)
    m = re.search(r"\b([0-9]+(?:\.[0-9]+)*)\b", title)
    if m:
        return m.group(1)
    return ""

def _task_key(task_num: str) -> Tuple[int, List[int]]:
    if task_num == "":
        return (999, (999999,))
    parts = [int(x) for x in task_num.split(".")]
    return (len(parts), tuple(parts))

def _parse_receiver(body: str) -> str:
    m = re.search(r"^Receiver Role \(Next step\):\s*(.+?)\s*$", body, re.M)
    return m.group(1).strip() if m else ""

def _guide_for_receiver(receiver: str) -> str:
    if receiver in ROLE_TO_GUIDE:
        return ROLE_TO_GUIDE[receiver]
    # tolerate short names
    if receiver.lower() == "qa lead":
        return "ROLE_QA.txt"
    if receiver.lower() == "code reviewer":
        return "ROLE_REVIEWER.txt"
    return "ROLE_TECH_LEAD.txt"

def _is_wi(issue: Dict[str, Any]) -> bool:
    if issue.get("pull_request") is not None:
        return False
    title = str(issue.get("title") or "")
    return title.startswith("WI-") or title.startswith("Work Item:")

def _is_ready(issue: Dict[str, Any]) -> bool:
    body = str(issue.get("body") or "")
    # Default to ready unless explicitly blocked
    if re.search(r"^Status:\s*Draft\b", body, re.M):
        return False
    return True

def _already_dispatched(issue: Dict[str, Any]) -> bool:
    # Avoid re-dispatch loops: look for marker comment
    # We use a comment marker because labels are optional.
    return False

def main() -> int:
    gh_token = os.environ.get("GITHUB_TOKEN", "")
    if gh_token == "":
        die("FD_FAIL: missing GITHUB_TOKEN")

    # Collect open issues
    all_issues: List[Dict[str, Any]] = []
    page = 1
    while True:
        batch = list_issues(gh_token, state="open", per_page=100, page=page)
        if not isinstance(batch, list) or len(batch) == 0:
            break
        all_issues.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    candidates: List[Tuple[Tuple[int, List[int]], int, str]] = []
    for it in all_issues:
        if not _is_wi(it):
            continue
        num = int(it.get("number"))
        # Fetch full body (list_issues body may be truncated)
        full = get_issue(num, gh_token)
        title = str(full.get("title") or "")
        body = str(full.get("body") or "")
        if not _is_ready(full):
            continue
        task_num = _parse_task_num(title, body)
        key = _task_key(task_num)
        candidates.append((key, num, task_num))

    if len(candidates) == 0:
        sys.stdout.write("FD_OK: no_open_wi\n")
        return 0

    candidates.sort(key=lambda x: (x[0][0], x[0][1], x[1]))

    next_issue_number = candidates[0][1]
    issue = get_issue(next_issue_number, gh_token)
    recv = _parse_receiver(str(issue.get("body") or ""))
    role_guide = _guide_for_receiver(recv)

    # Dispatch worker workflow. Keep ref=main (governance branch).
    workflow_dispatch(
        "run_wi_issue.yml",
        "main",
        {
            "issue_number": str(next_issue_number),
            "role_guide": role_guide,
        },
        gh_token,
    )

    create_comment(
        next_issue_number,
        "FD_DISPATCHED\nROLE_GUIDE=" + role_guide + "\n",
        gh_token,
    )
    sys.stdout.write("FD_OK: dispatched_issue=" + str(next_issue_number) + " role_guide=" + role_guide + "\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
