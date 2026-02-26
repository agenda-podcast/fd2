import json
import os
import time
import urllib.error
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

def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except Exception:
        return default

def _request(req: urllib.request.Request, timeout_s: int, retries: int) -> bytes:
    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            # Retry on 429 and transient 5xx.
            code = int(getattr(exc, "code", 0) or 0)
            body = b""
            try:
                body = exc.read()
            except Exception:
                pass
            if code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = min(2 ** (attempt - 1), 8)
                time.sleep(wait)
                last_err = RuntimeError("http " + str(code) + " retry")
                continue
            # Surface details.
            try:
                txt = body.decode("utf-8", errors="replace")
            except Exception:
                txt = ""
            raise RuntimeError("FD_FAIL: http " + str(code) + " " + txt) from exc
        except urllib.error.URLError as exc:
            # Network timeouts are usually transient on GitHub Actions.
            if attempt < retries:
                wait = min(2 ** (attempt - 1), 8)
                time.sleep(wait)
                last_err = exc
                continue
            raise RuntimeError("FD_FAIL: network error " + str(getattr(exc, "reason", exc))) from exc
        except TimeoutError as exc:
            if attempt < retries:
                wait = min(2 ** (attempt - 1), 8)
                time.sleep(wait)
                last_err = exc
                continue
            raise RuntimeError("FD_FAIL: timeout") from exc
    raise RuntimeError("FD_FAIL: request failed") from last_err

def get_issue(issue_number: int, token: str) -> Dict[str, Any]:
    timeout_s = _env_int("FD_HTTP_TIMEOUT_S", 60)
    retries = _env_int("FD_HTTP_RETRIES", 3)
    url = _api_base() + "/issues/" + str(issue_number)
    req = urllib.request.Request(url, headers=_headers(token), method="GET")
    data = _request(req, timeout_s, retries).decode("utf-8")
    return json.loads(data)

def create_issue(title: str, body: str, token: str) -> Dict[str, Any]:
    timeout_s = _env_int("FD_HTTP_TIMEOUT_S", 60)
    retries = _env_int("FD_HTTP_RETRIES", 3)
    url = _api_base() + "/issues"
    payload = json.dumps({"title": title, "body": body}).encode("utf-8")
    req = urllib.request.Request(url, headers=_headers(token), data=payload, method="POST")
    data = _request(req, timeout_s, retries).decode("utf-8")
    return json.loads(data)

def create_comment(issue_number: int, body: str, token: str) -> Dict[str, Any]:
    timeout_s = _env_int("FD_HTTP_TIMEOUT_S", 60)
    retries = _env_int("FD_HTTP_RETRIES", 3)
    url = _api_base() + "/issues/" + str(issue_number) + "/comments"
    payload = json.dumps({"body": body}).encode("utf-8")
    req = urllib.request.Request(url, headers=_headers(token), data=payload, method="POST")
    data = _request(req, timeout_s, retries).decode("utf-8")
    return json.loads(data)

def safe_get(obj: Dict[str, Any], key: str, default: str = "") -> str:
    v = obj.get(key)
    if v is None:
        return default
    return str(v)

def close_issue(issue_number: int, token: str) -> Dict[str, Any]:
    timeout_s = _env_int("FD_HTTP_TIMEOUT_S", 60)
    retries = _env_int("FD_HTTP_RETRIES", 3)
    url = _api_base() + "/issues/" + str(issue_number)
    payload = json.dumps({"state": "closed"}).encode("utf-8")
    req = urllib.request.Request(url, headers=_headers(token), data=payload, method="PATCH")
    data = _request(req, timeout_s, retries).decode("utf-8")
    return json.loads(data)

def list_open_issues(token: str, per_page: int = 100) -> Any:
    timeout_s = _env_int("FD_HTTP_TIMEOUT_S", 60)
    retries = _env_int("FD_HTTP_RETRIES", 3)
    url = _api_base() + "/issues?state=open&per_page=" + str(per_page)
    req = urllib.request.Request(url, headers=_headers(token), method="GET")
    data = _request(req, timeout_s, retries).decode("utf-8")
    return json.loads(data)

def dispatch_workflow(workflow_file: str, ref: str, inputs: Dict[str, str], token: str) -> None:
    timeout_s = _env_int("FD_HTTP_TIMEOUT_S", 60)
    retries = _env_int("FD_HTTP_RETRIES", 3)
    url = _api_base() + "/actions/workflows/" + workflow_file + "/dispatches"
    payload = json.dumps({"ref": ref, "inputs": inputs}).encode("utf-8")
    h = _headers(token)
    h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, headers=h, data=payload, method="POST")
    _request(req, timeout_s, retries)
