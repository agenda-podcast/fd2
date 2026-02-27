import io
import json
import os
import time
import urllib.request
import zipfile
from typing import Any, Dict, List, Optional, Tuple

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
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))

def _post_json(url: str, token: str, payload: Dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, headers=_headers(token), data=body, method="POST")
    req.add_header("content-type", "application/json; charset=utf-8")
    with urllib.request.urlopen(req, timeout=60):
        pass

def dispatch_workflow(workflow_file: str, ref: str, inputs: Dict[str, str], token: str) -> None:
    repo = _repo()
    wf = workflow_file.strip()
    if wf == "":
        raise RuntimeError("FD_FAIL: workflow_file empty")
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/dispatches"
    payload = {"ref": ref}
    if inputs:
        payload["inputs"] = inputs
    _post_json(url, token, payload)

def find_latest_run_id(workflow_file: str, branch: str, not_before_epoch: float, token: str, timeout_s: int = 180) -> int:
    repo = _repo()
    wf = workflow_file.strip()
    deadline = time.time() + timeout_s
    last_seen = 0
    while time.time() < deadline:
        url = f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/runs?per_page=20&branch={branch}&event=workflow_dispatch"
        data = _get_json(url, token)
        runs = data.get("workflow_runs") if isinstance(data, dict) else None
        if isinstance(runs, list):
            for r in runs:
                if not isinstance(r, dict):
                    continue
                created = r.get("created_at") or ""
                run_id = int(r.get("id") or 0)
                if run_id <= 0:
                    continue
                # created_at is ISO; compare by epoch via time.strptime rough
                try:
                    # 2026-02-27T00:00:00Z
                    tt = time.strptime(created, "%Y-%m-%dT%H:%M:%SZ")
                    epoch = time.mktime(tt)
                except Exception:
                    epoch = 0
                if epoch >= not_before_epoch and run_id > last_seen:
                    return run_id
                last_seen = max(last_seen, run_id)
        time.sleep(3)
    raise RuntimeError("FD_FAIL: could not find workflow run for " + wf + " branch=" + branch)

def wait_run_complete(run_id: int, token: str, timeout_s: int = 1800) -> Dict[str, Any]:
    repo = _repo()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}"
        data = _get_json(url, token)
        if isinstance(data, dict):
            status = str(data.get("status") or "")
            conclusion = str(data.get("conclusion") or "")
            if status == "completed":
                return data
        time.sleep(5)
    raise RuntimeError("FD_FAIL: workflow run timeout run_id=" + str(run_id))

def download_run_logs_zip(run_id: int, token: str) -> bytes:
    repo = _repo()
    url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/logs"
    req = urllib.request.Request(url, headers=_headers(token), method="GET")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()

def extract_logs_text(logs_zip: bytes, max_chars: int = 200000) -> str:
    buf = io.BytesIO(logs_zip)
    z = zipfile.ZipFile(buf, "r")
    texts: List[str] = []
    for name in z.namelist():
        if not name.endswith(".txt"):
            continue
        try:
            data = z.read(name).decode("utf-8", errors="ignore")
        except Exception:
            continue
        texts.append("### " + name + "\n" + data)
        if sum(len(x) for x in texts) > max_chars:
            break
    out = "\n\n".join(texts)
    if len(out) > max_chars:
        out = out[:max_chars]
    return out


def list_workflows(token: str) -> List[Dict[str, Any]]:
    repo = _repo()
    url = f"https://api.github.com/repos/{repo}/actions/workflows?per_page=100"
    data = _get_json(url, token)
    wfs = data.get("workflows") if isinstance(data, dict) else None
    if isinstance(wfs, list):
        return [w for w in wfs if isinstance(w, dict)]
    return []

def resolve_workflow_file(user_value: str, token: str) -> str:
    v = (user_value or "").strip()
    if v.endswith(".yml") or v.endswith(".yaml"):
        return v
    if v.startswith(".github/workflows/"):
        return v.replace(".github/workflows/","")
    wfs = list_workflows(token)
    for w in wfs:
        if str(w.get("name") or "") == v:
            p = str(w.get("path") or "")
            return p.replace(".github/workflows/","")
    for w in wfs:
        p = str(w.get("path") or "")
        if p.endswith("/" + v):
            return v
    return v
