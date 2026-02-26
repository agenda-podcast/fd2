import re
from typing import List, Tuple

from src.github_api import list_open_issues

def _extract_field(text: str, key: str) -> str:
    for line in text.splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return ""

def _parse_task_number(task_num: str) -> Tuple[int, List[int]]:
    s = task_num.strip()
    if s == "":
        return (9999, (9999,))
    if not re.match(r"^[0-9]+(\.[0-9]+)*$", s):
        return (9999, (9999,))
    parts = [int(x) for x in s.split(".")]
    depth = len(parts)
    return (depth, parts)

def _wi_numeric_from_title(title: str) -> int:
    m = re.search(r"\bWI-([0-9]{3,})\b", title)
    if not m:
        return 0
    try:
        return int(m.group(1))
    except Exception:
        return 0

def pick_next_wi_issue_number(token: str) -> int:
    issues = list_open_issues(token)
    candidates: List[Tuple[int, List[int], int, int]] = []
    for it in issues:
        if isinstance(it, dict) and it.get("pull_request") is not None:
            continue
        title = str(it.get("title", ""))
        if not title.startswith("Work Item:") and "WI-" not in title:
            continue
        body = str(it.get("body", "") or "")
        task_num = _extract_field(body, "Task Number")
        depth, pair = _parse_task_number(task_num)
        wi_num = _wi_numeric_from_title(title)
        issue_no = int(it.get("number", 0))
        candidates.append((depth, pair, wi_num, issue_no))
    if not candidates:
        return 0
    candidates.sort(key=lambda x: (x[0],) + tuple(x[1]) + (x[2], x[3]))
    return candidates[0][3]
