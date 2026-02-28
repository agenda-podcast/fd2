import io
import json
import os
import time
import urllib.request
import urllib.error

import zipfile
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

from typing import Any, Dict, List

def _read_http_error_body(e: urllib.error.HTTPError) -> str:
    try:
        b = e.read()
        if not b:
            return ""
        return b.decode("utf-8", errors="replace")
    except Exception:
        return ""

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

def _get_json(url: str, token: str) -> Any:
    req = urllib.request.Request(url, headers=_headers(token), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = _read_http_error_body(e)
        raise RuntimeError("FD_GH_HTTP_ERROR method=GET url=" + url + " status=" + str(e.code) + " body=" + body) from e

def _post_json(url: str, token: str, payload: Dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, headers=_headers(token), data=body, method="POST")
    req.add_header("content-type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=60):
            pass
    except urllib.error.HTTPError as e:
        eb = _read_http_error_body(e)
        raise RuntimeError("FD_GH_HTTP_ERROR method=POST url=" + url + " status=" + str(e.code) + " body=" + eb) from e

def dispatch_workflow(workflow_file: str, ref: str, inputs: Dict[str, str], token: str) -> None:
    repo = _repo()
    wf = workflow_file.strip()
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/dispatches"
    payload: Dict[str, Any] = {"ref": ref}
    if inputs:
        payload["inputs"] = inputs
    _post_json(url, token, payload)

def find_latest_run_id(workflow_file: str, branch: str, not_before_epoch: float, token: str, timeout_s: int = 180) -> int:
    repo = _repo()
    wf = workflow_file.strip()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        url = f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/runs?per_page=20&branch={branch}&event=workflow_dispatch"
        data = _get_json(url, token)
        runs = data.get("workflow_runs") if isinstance(data, dict) else None
        if isinstance(runs, list):
            for r in runs:
                if not isinstance(r, dict):
                    continue
                created = str(r.get("created_at") or "")
                run_id = int(r.get("id") or 0)
                if run_id <= 0:
                    continue
                try:
                    tt = time.strptime(created, "%Y-%m-%dT%H:%M:%SZ")
                    epoch = time.mktime(tt)
                except Exception:
                    epoch = 0
                if epoch >= not_before_epoch:
                    return run_id
        time.sleep(3)
    raise RuntimeError("FD_FAIL: could not find workflow run for " + wf + " branch=" + branch)

def wait_run_complete(run_id: int, token: str, timeout_s: int = 3600) -> Dict[str, Any]:
    repo = _repo()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}"
        data = _get_json(url, token)
        if isinstance(data, dict):
            if str(data.get("status") or "") == "completed":
                return data
        time.sleep(5)
    raise RuntimeError("FD_FAIL: workflow run timeout run_id=" + str(run_id))

def download_run_logs_zip(run_id: int, token: str) -> bytes:
    repo = _repo()
    url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/logs"
    req = urllib.request.Request(url, headers=_headers(token), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        body = _read_http_error_body(e)
        raise RuntimeError("FD_GH_HTTP_ERROR method=GET url=" + url + " status=" + str(e.code) + " body=" + body) from e

def extract_logs_text(logs_zip: bytes, max_chars: int = 400000) -> str:
    buf = io.BytesIO(logs_zip)
    z = zipfile.ZipFile(buf, "r")
    texts: List[str] = []
    total = 0
    for name in z.namelist():
        if not name.endswith(".txt"):
            continue
        try:
            data = z.read(name).decode("utf-8", errors="ignore")
        except Exception:
            continue
        block = "### " + name + "\n" + data
        texts.append(block)
        total += len(block)
        if total > max_chars:
            break
    out = "\n\n".join(texts)
    if len(out) > max_chars:
        out = out[:max_chars]
    return out

def list_run_artifacts(run_id: int, token: str) -> List[Dict[str, Any]]:
    repo = _repo()
    url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100"
    data = _get_json(url, token)
    arts = data.get("artifacts") if isinstance(data, dict) else None
    if isinstance(arts, list):
        return [a for a in arts if isinstance(a, dict)]
    return []

def download_artifact_zip(artifact_id: int, token: str) -> bytes:
    repo = _repo()
    url = f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}/zip"
    req = urllib.request.Request(url, headers=_headers(token), method="GET")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=120) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        # GitHub returns 302 to a signed URL; follow it without auth headers.
        if e.code in (301, 302, 303, 307, 308):
            loc = e.headers.get("Location") or e.headers.get("location") or ""
            if loc:
                req2 = urllib.request.Request(loc, method="GET")
                with urllib.request.urlopen(req2, timeout=120) as resp2:
                    return resp2.read()
        raise
