import re
from typing import List, Tuple, Optional, Set

from src.github_api import list_open_issues

def _extract_field(text: str, key: str) -> str:
    for line in text.splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return ""

def _parse_task_number(task_num: str) -> List[int]:
    s = task_num.strip()
    if s == "":
        return []
    if not re.match(r"^[0-9]+(\.[0-9]+)*$", s):
        return []
    return [int(x) for x in s.split(".") if x.strip() != ""]

def _wi_numeric_from_title(title: str) -> int:
    m = re.search(r"\bWI-([0-9]{3,})\b", title)
    if not m:
        return 0
    try:
        return int(m.group(1))
    except Exception:
        return 0

def _task_sort_key(parts: List[int]) -> Tuple[int, int, int, int, int, int, int, int]:
    # Best-practice ordering for dotted task numbers:
    # 1, 1.1, 1.2, 2, 2.1, 10, etc
    # Achieve this by padding the tuple with large sentinels.
    if not parts:
        return (9999,)
    pad = 8
    padded = parts[:pad] + [9999] * max(0, pad - len(parts))
    return tuple(padded)

def pick_next_wi_issue_number(token: str, exclude: Optional[Set[int]] = None) -> int:
    issues = list_open_issues(token)
    ex = exclude or set()
    candidates: List[Tuple[Tuple[int, int, int, int, int, int, int, int], int, int]] = []
    for it in issues:
        if isinstance(it, dict) and it.get("pull_request") is not None:
            continue
        issue_no = int(it.get("number", 0))
        if issue_no in ex:
            continue
        title = str(it.get("title", ""))
        if not title.startswith("Work Item:") and "WI-" not in title:
            continue
        body = str(it.get("body", "") or "")
        task_num = _extract_field(body, "Task Number")
        parts = _parse_task_number(task_num)
        wi_num = _wi_numeric_from_title(title)
        candidates.append((_task_sort_key(parts), wi_num, issue_no))
    if not candidates:
        return 0
    # Primary: task number (dotted) ascending. Secondary: WI numeric, then issue number.
    candidates.sort(key=lambda x: (x[0], x[1], x[2]))
    return candidates[0][2]
