#!/usr/bin/env python3
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.fd_manifest import load_manifest_from_text
from src.github_api import get_issue, safe_get

MAX_PAGES = 20
PER_PAGE = 100

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

def _get_json(url: str, token: str) -> Any:
    req = urllib.request.Request(url, headers=_headers(token), method="GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read().decode("utf-8")
    return json.loads(data)

def _download(url: str, token: str) -> bytes:
    h = _headers(token)
    # Some assets require the API accept header; browser_download_url usually works with auth.
    req = urllib.request.Request(url, headers=h, method="GET")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()

def _list_issues(token: str, state: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        url = _api_base() + "/issues?state=" + state + "&per_page=" + str(PER_PAGE) + "&page=" + str(page)
        items = _get_json(url, token)
        if not isinstance(items, list) or len(items) == 0:
            break
        out.extend([x for x in items if isinstance(x, dict)])
    return out

def _list_issue_comments(issue_number: int, token: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        url = _api_base() + "/issues/" + str(issue_number) + "/comments?per_page=" + str(PER_PAGE) + "&page=" + str(page)
        items = _get_json(url, token)
        if not isinstance(items, list) or len(items) == 0:
            break
        out.extend([x for x in items if isinstance(x, dict)])
    return out

def _extract_field(text: str, key: str) -> str:
    for line in (text or "").splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return ""

def _parse_task_number(task_num: str) -> Tuple[int, int, int, int, int, int, int, int]:
    s = (task_num or "").strip()
    if s == "":
        return (9999, 9999, 9999, 9999, 9999, 9999, 9999, 9999)
    if not re.match(r"^[0-9]+(\.[0-9]+)*$", s):
        return (9999, 9999, 9999, 9999, 9999, 9999, 9999, 9999)
    parts = [int(x) for x in s.split(".") if x.strip() != ""]
    pad = 8
    padded = parts[:pad] + [9999] * max(0, pad - len(parts))
    return tuple(padded)

def _wi_numeric_from_title(title: str) -> int:
    m = re.search(r"\bWI-([0-9]{3,})\b", title or "")
    if not m:
        return 0
    try:
        return int(m.group(1))
    except Exception:
        return 0

def _find_release_tag_from_comments(comments: List[Dict[str, Any]]) -> str:
    tag = ""
    for c in comments:
        body = safe_get(c, "body", "")
        if "FD_WI_DONE" not in body:
            continue
        for line in body.splitlines():
            if line.startswith("RELEASE="):
                tag = line.split("=", 1)[1].strip()
    return tag

def _get_release_by_tag(tag: str, token: str) -> Dict[str, Any]:
    url = _api_base() + "/releases/tags/" + tag
    obj = _get_json(url, token)
    if not isinstance(obj, dict):
        raise RuntimeError("FD_FAIL: release not found tag=" + tag)
    return obj

def _download_release_asset(release: Dict[str, Any], name: str, token: str) -> bytes:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise RuntimeError("FD_FAIL: release assets missing")
    for a in assets:
        if not isinstance(a, dict):
            continue
        if safe_get(a, "name") == name:
            url = safe_get(a, "browser_download_url")
            if url == "":
                raise RuntimeError("FD_FAIL: asset url missing name=" + name)
            return _download(url, token)
    raise RuntimeError("FD_FAIL: asset not found name=" + name)

def _unzip_bytes(zbytes: bytes, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(zbytes), "r") as z:
        z.extractall(dest)

def _iter_files(root: Path) -> List[Path]:
    out: List[Path] = []
    for dp, dn, fn in os.walk(root):
        if ".git" in dn:
            dn.remove(".git")
        for f in fn:
            out.append(Path(dp) / f)
    return out

def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

def _same_bytes(a: Path, b: Path) -> bool:
    try:
        if not a.exists() or not b.exists():
            return False
        if a.stat().st_size != b.stat().st_size:
            return False
        return a.read_bytes() == b.read_bytes()
    except Exception:
        return False

def _normalize_layout(stage: Path) -> None:
    # Move pipeline_app/* to root if present.
    for folder in ["pipeline_app", "app"]:
        src = stage / folder
        if not src.exists() or not src.is_dir():
            continue
        for item in list(src.iterdir()):
            dst = stage / item.name
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True)
            else:
                _copy_file(item, dst)
        shutil.rmtree(src, ignore_errors=True)

def _remove_workflows(stage: Path) -> None:
    wf = stage / ".github" / "workflows"
    if wf.exists():
        shutil.rmtree(wf, ignore_errors=True)

def _build_base_for_diff(repo_root: Path) -> Path:
    base = Path(tempfile.mkdtemp(prefix="fd_base_"))
    pb = repo_root / "pipeline_base" / "pipeline_app"
    if pb.exists():
        shutil.copytree(pb, base / "pipeline_app", dirs_exist_ok=True)
    return base

def assemble_stage_for_ms(ms_id: str, token: str, repo_root: Path) -> Path:
    issues = _list_issues(token, "open") + _list_issues(token, "closed")
    wi: List[Tuple[Tuple[int, int, int, int, int, int, int, int], int, int, int]] = []
    # tuple: (task_key, wi_num, issue_no, issue_no)
    for it in issues:
        if it.get("pull_request") is not None:
            continue
        body = safe_get(it, "body", "")
        if ("Milestone ID: " + ms_id) not in body:
            continue
        title = safe_get(it, "title", "")
        if not title.startswith("Work Item:") and "WI-" not in title:
            continue
        issue_no = int(it.get("number", 0))
        tn = _extract_field(body, "Task Number")
        wi_num = _wi_numeric_from_title(title)
        wi.append((_parse_task_number(tn), wi_num, issue_no, issue_no))
    if not wi:
        raise RuntimeError("FD_FAIL: no WI issues found for milestone " + ms_id)
    wi.sort(key=lambda x: (x[0], x[1], x[2]))

    base_for_diff = _build_base_for_diff(repo_root)
    stage = Path(tempfile.mkdtemp(prefix="fd_assembled_"))

    # Start from existing app branch if it exists; otherwise empty stage.
    # We intentionally keep this tool pure file assembly. Branch publish is handled by caller.
    # Caller may pass stage as base and merge into git working tree.
    print("FD_DEBUG: assemble_start ms=" + ms_id + " wi_count=" + str(len(wi)))

    for (_, _, issue_no, _) in wi:
        issue = get_issue(issue_no, token)
        body = safe_get(issue, "body", "")
        title = safe_get(issue, "title", "")
        tn = _extract_field(body, "Task Number")
        comments = _list_issue_comments(issue_no, token)
        tag = _find_release_tag_from_comments(comments)
        if tag == "":
            print("FD_WARN: wi missing release tag issue=" + str(issue_no) + " title=" + title)
            continue
        release = _get_release_by_tag(tag, token)
        manifest_bytes = _download_release_asset(release, "manifest.json", token)
        artifact_bytes = _download_release_asset(release, "artifact.zip", token)

        manifest = load_manifest_from_text(manifest_bytes.decode("utf-8", errors="strict"))
        wi_type = manifest.artifact_type
        print("FD_DEBUG: apply_wi issue=" + str(issue_no) + " task=" + tn + " tag=" + tag + " type=" + wi_type)

        wi_root = Path(tempfile.mkdtemp(prefix="fd_wi_zip_"))
        _unzip_bytes(artifact_bytes, wi_root)

        # artifact.zip includes a folder root; normalize by taking first directory if it exists.
        entries = [p for p in wi_root.iterdir()]
        wi_stage = wi_root
        if len(entries) == 1 and entries[0].is_dir():
            wi_stage = entries[0]

        if wi_type == "pipeline_snapshot":
            # Replace stage with snapshot.
            shutil.rmtree(stage, ignore_errors=True)
            stage = Path(tempfile.mkdtemp(prefix="fd_assembled_"))
            shutil.copytree(wi_stage, stage, dirs_exist_ok=True)
        else:
            # repo_patch: compute deltas vs base_for_diff and overlay onto stage.
            for f in _iter_files(wi_stage):
                rel = f.relative_to(wi_stage)
                base_f = base_for_diff / rel
                dst = stage / rel
                if not base_f.exists():
                    _copy_file(f, dst)
                else:
                    if not _same_bytes(f, base_f):
                        _copy_file(f, dst)
            for d in manifest.delete:
                if d.strip() == "":
                    continue
                target = stage / d
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                elif target.exists():
                    try:
                        target.unlink()
                    except Exception:
                        pass

    _normalize_layout(stage)
    _remove_workflows(stage)
    print("FD_DEBUG: assemble_done stage=" + str(stage))
    return stage

def main() -> int:
    if len(os.sys.argv) < 2:
        print("FD_FAIL: missing ms_id")
        return 2
    ms_id = os.sys.argv[1].strip()
    token = os.environ.get("FD_BOT_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
    if token == "":
        print("FD_FAIL: missing token")
        return 2
    repo_root = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    stage = assemble_stage_for_ms(ms_id, token, repo_root)
    out_dir = os.environ.get("FD_ASSEMBLE_OUT", "")
    if out_dir != "":
        dst = Path(out_dir)
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(stage, dst, dirs_exist_ok=True)
        print("FD_OK: assembled_to=" + str(dst))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
