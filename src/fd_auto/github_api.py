import json
import os
import urllib.request
from typing import Any, Dict, List

def _repo() -> str:
    r = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
    if r == "":
        raise RuntimeError("FD_FAIL: missing GITHUB_REPOSITORY")
    return r

def _headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "fd-auto",
    }

def safe_get(d: Any, key: str, default: Any = "") -> Any:
    if isinstance(d, dict) and key in d:
        return d[key]
    return default

def get_issue(issue_number: int, token: str) -> Dict[str, Any]:
    repo = _repo()
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
    req = urllib.request.Request(url, headers=_headers(token), method="GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))

def create_comment(issue_number: int, body: str, token: str) -> None:
    repo = _repo()
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    payload = json.dumps({"body": body}).encode("utf-8")
    req = urllib.request.Request(url, headers=_headers(token), data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=60):
        pass

def list_issues(token: str, state: str = "open") -> List[Dict[str, Any]]:
    repo = _repo()
    url = f"https://api.github.com/repos/{repo}/issues?state={state}&per_page=100"
    req = urllib.request.Request(url, headers=_headers(token), method="GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))

def list_comments(issue_number: int, token: str) -> List[Dict[str, Any]]:
    repo = _repo()
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments?per_page=100"
    req = urllib.request.Request(url, headers=_headers(token), method="GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))
