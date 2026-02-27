#!/usr/bin/env python3
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.fd_bundle_v1 import parse_bundle_parts
from src.fd_apply import apply_manifest
from src.github_api import safe_get

MAX_PAGES = 10
PER_PAGE = 100

def _token() -> str:
    t = os.environ.get("FD_BOT_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
    if t == "":
        raise RuntimeError("FD_FAIL: missing token")
    return t

def _repo() -> str:
    r = os.environ.get("GITHUB_REPOSITORY", "")
    if r == "":
        raise RuntimeError("FD_FAIL: missing GITHUB_REPOSITORY")
    return r

def _headers(token: str) -> Dict[str, str]:
    return {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "User-Agent": "fd-orchestrator"}

def _get_json(url: str, token: str) -> Any:
    req = urllib.request.Request(url, headers=_headers(token), method="GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))

def _download(url: str, token: str) -> bytes:
    req = urllib.request.Request(url, headers=_headers(token), method="GET")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()

def _extract_field(text: str, key: str) -> str:
    for line in (text or "").splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return ""

def _task_key(s: str) -> Tuple[int, int, int, int, int, int, int, int]:
    t = (s or "").strip()
    if not re.match(r"^[0-9]+(\.[0-9]+)*$", t):
        return (9999, 9999, 9999, 9999, 9999, 9999, 9999, 9999)
    parts = [int(x) for x in t.split(".")]
    pad = 8
    parts = parts[:pad] + [9999] * max(0, pad - len(parts))
    return tuple(parts)

def _list_issues(token: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    repo = _repo()
    for state in ["open", "closed"]:
        for page in range(1, MAX_PAGES + 1):
            url = "https://api.github.com/repos/" + repo + "/issues?state=" + state + "&per_page=" + str(PER_PAGE) + "&page=" + str(page)
            items = _get_json(url, token)
            if not isinstance(items, list) or len(items) == 0:
                break
            for it in items:
                if isinstance(it, dict) and it.get("pull_request") is None:
                    out.append(it)
    return out

def _list_comments(issue_number: int, token: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    repo = _repo()
    for page in range(1, MAX_PAGES + 1):
        url = "https://api.github.com/repos/" + repo + "/issues/" + str(issue_number) + "/comments?per_page=" + str(PER_PAGE) + "&page=" + str(page)
        items = _get_json(url, token)
        if not isinstance(items, list) or len(items) == 0:
            break
        for it in items:
            if isinstance(it, dict):
                out.append(it)
    return out

def _find_release_tag(comments: List[Dict[str, Any]]) -> str:
    tag = ""
    for c in comments:
        body = safe_get(c, "body", "")
        if "RELEASE=" not in body:
            continue
        for line in body.splitlines():
            if line.startswith("RELEASE="):
                tag = line.split("=", 1)[1].strip()
    return tag

def _get_release(tag: str, token: str) -> Dict[str, Any]:
    repo = _repo()
    url = "https://api.github.com/repos/" + repo + "/releases/tags/" + tag
    obj = _get_json(url, token)
    if not isinstance(obj, dict):
        raise RuntimeError("FD_FAIL: release not found tag=" + tag)
    return obj

def _download_asset(release: Dict[str, Any], name: str, token: str) -> bytes:
    assets = release.get("assets") or []
    for a in assets:
        if isinstance(a, dict) and safe_get(a, "name") == name:
            url = safe_get(a, "browser_download_url")
            if url == "":
                raise RuntimeError("FD_FAIL: asset url missing name=" + name)
            return _download(url, token)
    raise RuntimeError("FD_FAIL: asset not found name=" + name)

def _read_bundle_parts_from_artifact_zip(artifact_zip_bytes: bytes) -> List[str]:
    tmp = Path(tempfile.mkdtemp(prefix="fd_bundle_art_"))
    with zipfile.ZipFile(io.BytesIO(artifact_zip_bytes), "r") as z:
        z.extractall(tmp)
    parts = []
    for p in sorted(tmp.rglob("bundle_part_*.txt")):
        parts.append(p.read_text(encoding="utf-8", errors="ignore"))
    if parts:
        return parts
    full = list(tmp.rglob("bundle_full.txt"))
    if full:
        return [full[0].read_text(encoding="utf-8", errors="ignore")]
    raise RuntimeError("FD_FAIL: bundle files not found in artifact")

def main() -> int:
    if len(os.sys.argv) < 2:
        print("usage: publish_app_branch_from_ms.py MS-01")
        return 2
    ms_id = os.sys.argv[1].strip()
    token = _token()

    issues = _list_issues(token)
    builder = []
    for it in issues:
        body = safe_get(it, "body", "")
        if ("Milestone ID: " + ms_id) not in body:
            continue
        tn = _extract_field(body, "Task Number")
        prod = _extract_field(body, "Owner Role (Producer)")
        if tn.strip() in ("1", "2", "3") and "Builder" in prod:
            builder.append((_task_key(tn), int(it.get("number", 0))))
    builder.sort(key=lambda x: x[0])
    if len(builder) != 3:
        raise RuntimeError("FD_FAIL: expected 3 Builder WIs for milestone " + ms_id + " got=" + str(len(builder)))

    stage = Path(tempfile.mkdtemp(prefix="fd_app_stage_"))
    for _, issue_no in builder:
        comments = _list_comments(issue_no, token)
        tag = _find_release_tag(comments)
        if tag == "":
            raise RuntimeError("FD_FAIL: missing RELEASE tag in comments for issue " + str(issue_no))
        rel = _get_release(tag, token)
        art = _download_asset(rel, "artifact.zip", token)
        parts = _read_bundle_parts_from_artifact_zip(art)
        manifest = parse_bundle_parts(parts)
        apply_manifest(manifest, stage)

    wf = stage / ".github" / "workflows"
    if wf.exists():
        shutil.rmtree(wf, ignore_errors=True)

    repo_root = Path(os.getcwd())
    branch = "app-" + ms_id.lower()
    subprocess.check_call(["git", "checkout", "-B", branch], cwd=str(repo_root))
    for entry in os.listdir(repo_root):
        if entry == ".git":
            continue
        p = repo_root / entry
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            try:
                p.unlink()
            except Exception:
                pass
    for entry in os.listdir(stage):
        src = stage / entry
        dst = repo_root / entry
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    subprocess.check_call(["git", "add", "-A"], cwd=str(repo_root))
    try:
        subprocess.check_call(["git", "commit", "-m", "Publish app from bundles " + ms_id], cwd=str(repo_root))
    except Exception:
        pass

    repo_name = _repo()
    remote_url = "https://x-access-token:" + token + "@github.com/" + repo_name + ".git"
    subprocess.check_call(["git", "remote", "set-url", "origin", remote_url], cwd=str(repo_root))
    try:
        subprocess.check_call(["git", "fetch", "origin", branch], cwd=str(repo_root))
    except Exception:
        pass
    subprocess.check_call(["git", "push", "-u", "origin", branch, "--force-with-lease"], cwd=str(repo_root))
    print("FD_OK: published branch " + branch)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
