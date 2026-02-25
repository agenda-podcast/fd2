import json
import os
import urllib.request
from typing import Any, Dict, Optional


def _api_base() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if repo == "":
        raise RuntimeError("FD_FAIL: missing GITHUB_REPOSITORY")
    return "https://api.github.com/repos/" + repo


def _headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "fd-orchestrator",
    }


def get_issue(issue_number: int, token: str) -> Dict[str, Any]:
    url = _api_base() + "/issues/" + str(issue_number)
    req = urllib.request.Request(url, headers=_headers(token), method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read().decode("utf-8")
    return json.loads(data)


def create_issue(title: str, body: str, token: str) -> Dict[str, Any]:
    url = _api_base() + "/issues"
    payload = json.dumps({"title": title, "body": body}).encode("utf-8")
    req = urllib.request.Request(url, headers=_headers(token), data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read().decode("utf-8")
    return json.loads(data)


def create_comment(issue_number: int, body: str, token: str) -> Dict[str, Any]:
    url = _api_base() + "/issues/" + str(issue_number) + "/comments"
    payload = json.dumps({"body": body}).encode("utf-8")
    req = urllib.request.Request(url, headers=_headers(token), data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read().decode("utf-8")
    return json.loads(data)


def safe_get(obj: Dict[str, Any], key: str, default: str = "") -> str:
    v = obj.get(key)
    if v is None:
        return default
    return str(v)
