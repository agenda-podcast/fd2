#!/usr/bin/env python3
import datetime
import glob
import os
import subprocess
import sys
import tempfile
import traceback
import time
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.getcwd()))

from src.fd_auto.actions_api import dispatch_workflow, find_latest_run_id, wait_run_complete, download_run_logs_zip, extract_logs_text
from src.fd_auto.gemini_client import call_gemini
from src.fd_auto.patch_parse import parse_bundle_parts, bundle_total_parts
from src.fd_auto.apply_patch import apply_patch
from src.fd_auto.util import first_n_lines
from tools.fd_auto_apply_snapshot import apply_snapshot

def _run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

def _write(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8", errors="ignore")

def _call_bundle(prompt: str, out_dir: Path) -> list[str]:
    parts = []
    first = call_gemini(prompt, timeout_s=900)
    parts.append(first)
    _write(out_dir / "part_1.txt", first)
    x, y = bundle_total_parts(first)
    if y <= 1:
        return parts
    cur = x
    while cur < y and cur < 8:
        cur += 1
        cont = prompt + "\n\nCONTINUE\nReturn ONLY: FD_BUNDLE_V1 PART " + str(cur) + "/" + str(y) + "\nDo not repeat earlier parts.\n"
        nxt = call_gemini(cont, timeout_s=900)
        parts.append(nxt)
        _write(out_dir / ("part_" + str(cur) + ".txt"), nxt)
    _write(out_dir / "bundle_full.txt", "\n\n".join(parts))
    return parts

def _upload_snapshot_chunks(snapshot_text: str, out_dir: Path) -> None:
    if snapshot_text.strip() == "":
        return
    max_chars = int(os.environ.get("FD_SNAPSHOT_MAX_CHARS","180000") or "180000")
    chunk_chars = int(os.environ.get("FD_SNAPSHOT_CHUNK_CHARS","50000") or "50000")
    txt = snapshot_text[:max_chars]
    total = (len(txt) + chunk_chars - 1) // chunk_chars
    if total < 1:
        total = 1
    for i in range(total):
        a = i * chunk_chars
        b = min(len(txt), (i + 1) * chunk_chars)
        chunk = txt[a:b]
        prompt = ""
        prompt += "ROLE: BUILDER\n"
        prompt += "TASK: Receive repository snapshot chunk. Do not propose fixes yet.\n"
        prompt += "INSTRUCTION: Reply with exactly: ACK " + str(i+1) + "/" + str(total) + "\n"
        prompt += "SNAPSHOT_CHUNK " + str(i+1) + "/" + str(total) + "\n"
        prompt += chunk + "\n"
        _write(out_dir / ("snapshot_chunk_" + str(i+1) + "_prompt.txt"), prompt)
        resp = call_gemini(prompt, timeout_s=900)
        _write(out_dir / ("snapshot_chunk_" + str(i+1) + "_response.txt"), resp)

def _get_fix_bundle_and_parse(base_prompt: str, out_dir: Path, max_tries: int = 3):
    last_err = ""
    for k in range(1, max_tries + 1):
        prompt = base_prompt
        if k > 1:
            prompt += "\n\nFORMAT_REPAIR\nPrevious output failed to parse: " + last_err + "\n"
            prompt += "Return ONLY FD_BUNDLE_V1 PART 1/Y.\n"
            prompt += "The FIRST line must be: FD_BUNDLE_V1 PART 1/Y\n"
            prompt += "Metadata lines MUST be key: value (with colon), e.g. work_item_id: WI-XYZ\n"
            prompt += "File blocks MUST use: FILE: path (with colon)\n"
            prompt += "Every FILE block MUST have <<< and >>>.\n"
            prompt += "No markdown fences. No prose.\n"
        parts = _call_bundle(prompt, out_dir / ("gen_try_" + str(k)))
        try:
            patch = parse_bundle_parts(parts)
            return (patch, parts, "")
        except Exception as exc:
            last_err = str(exc)
            _write(out_dir / ("parse_error_try_" + str(k) + ".txt"), last_err + "\n")
            continue
    return (None, [], last_err)

def _summarize_logs(logs_text: str) -> str:
    if not logs_text:
        return ""
    lines = logs_text.splitlines()
    patterns = ["Error:", "ERROR", "Traceback", "Exception", "FAILED", "Failure", "FD_FAIL", "FD_POLICY_FAIL", "UnboundLocalError", "ModuleNotFoundError"]
    hits = []
    for i, line in enumerate(lines):
        for p in patterns:
            if p in line:
                start = max(0, i - 2)
                end = min(len(lines), i + 3)
                snippet = "\n".join(lines[start:end])
                hits.append("----\nline=" + str(i+1) + "\n" + snippet)
                break
        if len(hits) >= 40:
            break
    head = "\n".join(lines[:120])
    out = []
    out.append("LOG_HEAD_BEGIN")
    out.append(head)
    out.append("LOG_HEAD_END")
    out.append("")
    out.append("DISCREPANCIES_BEGIN")
    out.extend(hits)
    out.append("DISCREPANCIES_END")
    return "\n".join(out) + "\n"

def _parse_inputs(s: str) -> dict:
    out = {}
    for line in (s or "").splitlines():
        t = line.strip()
        if t == "" or t.startswith("#"):
            continue
        if "=" not in t:
            continue
        k, v = t.split("=", 1)
        out[k.strip()] = v.strip()
    return out

def _set_origin_with_token(repo_root: Path, token: str) -> None:
    repo = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
    if repo == "":
        raise RuntimeError("FD_FAIL: missing GITHUB_REPOSITORY")
    remote_url = "https://x-access-token:" + token + "@github.com/" + repo + ".git"
    subprocess.check_call(["git","remote","set-url","origin",remote_url], cwd=str(repo_root))

def _ensure_worktree(branch: str) -> tuple[Path, str]:
    repo_root = Path(os.getcwd())
    wt_dir = Path(tempfile.mkdtemp(prefix="fd_tune_wt_"))
    # fetch branch
    subprocess.check_call(["git","fetch","origin",branch], cwd=str(repo_root))
    subprocess.check_call(["git","worktree","add",str(wt_dir),branch], cwd=str(repo_root))
    return wt_dir, str(repo_root)

def _read_latest_snapshot(wt_dir: Path) -> str:
    snap_dir = wt_dir / "docs" / "assets" / "app"
    snaps = sorted([str(p) for p in snap_dir.glob("app-source_*.txt")]) if snap_dir.exists() else []
    if not snaps:
        return ""
    return Path(snaps[-1]).read_text(encoding="utf-8", errors="ignore")

def main() -> int:
    if len(sys.argv) < 4:
        print("usage: fd_auto_tune_branch.py <branch> <workflow_file> <max_attempts> [workflow_inputs]")
        return 2
    branch = sys.argv[1].strip()
    workflow_file = sys.argv[2].strip()
    max_attempts = int((sys.argv[3].strip() or "10"))
    workflow_inputs = sys.argv[4] if len(sys.argv) > 4 else ""

    token = (os.environ.get("FD_BOT_TOKEN") or "").strip()
    if token == "":
        raise RuntimeError("FD_FAIL: missing FD_BOT_TOKEN")
    if max_attempts < 1:
        max_attempts = 1

    print("FD_DEBUG: tune_config branch=" + branch + " workflow_file=" + workflow_file + " max_attempts=" + str(max_attempts))

    artifacts = Path(tempfile.mkdtemp(prefix="fd_tune_artifacts_"))
    _write(artifacts / "branch.txt", branch + "\n")
    _write(artifacts / "workflow_file.txt", workflow_file + "\n")
    _write(artifacts / "workflow_inputs.txt", workflow_inputs + "\n")

    wt_dir, repo_root = _ensure_worktree(branch)
    _set_origin_with_token(Path(repo_root), token)

    for attempt in range(1, max_attempts + 1):
        print("FD_DEBUG: attempt_begin " + str(attempt) + "/" + str(max_attempts))
        try:
            # Create snapshot if missing
            subprocess.check_call([sys.executable, os.path.join(repo_root, "tools", "fd_auto_make_snapshot.py")], cwd=str(wt_dir))

            # Dispatch workflow on the branch and collect logs
            inputs = _parse_inputs(workflow_inputs)
            start_epoch = time.time()
            _write(artifacts / ("attempt_" + str(attempt) + "_dispatch.txt"), "branch=" + branch + "\nworkflow_file=" + workflow_file + "\ninputs=" + str(inputs) + "\n")
            dispatch_workflow(workflow_file, branch, inputs, token)
            run_id = find_latest_run_id(workflow_file, branch, start_epoch - 5, token, timeout_s=180)
            run_info = wait_run_complete(run_id, token, timeout_s=3600)
            logs_zip = download_run_logs_zip(run_id, token)
            logs_text = extract_logs_text(logs_zip, max_chars=250000)
            _write(artifacts / ("run_" + str(run_id) + "_attempt_" + str(attempt) + ".log"), logs_text)
            summary = ""
            summary += "RUN_ID=" + str(run_id) + "\n"
            summary += "STATUS=" + status + "\n"
            summary += "CONCLUSION=" + conclusion + "\n"
            html_url = str(run_info.get("html_url") or "")
            if html_url:
                summary += "URL=" + html_url + "\n"
            summary += "\n" + _summarize_logs(logs_text)
            _write(artifacts / ("attempt_" + str(attempt) + "_workflow_summary.txt"), summary)

            status = str(run_info.get("status") or "")
            conclusion = str(run_info.get("conclusion") or "")
            if status == "completed" and conclusion == "success":
                print("FD_OK: workflow green run_id=" + str(run_id))
                return 0

            snapshot_text = _read_latest_snapshot(wt_dir)
            _write(artifacts / ("snapshot_path_attempt_" + str(attempt) + ".txt"), "exists=" + ("1" if snapshot_text.strip() else "0") + "\n")
            _upload_snapshot_chunks(snapshot_text, artifacts / ("snapshot_upload_attempt_" + str(attempt)))

            prompt = ""
            prompt += "ROLE: BUILDER\n"
            prompt += "TASK: Fix the repository so the dispatched workflow passes on branch " + branch + ".\n"
            prompt += "WORKFLOW_FILE=" + workflow_file + "\n"
            prompt += "OUTPUT: FD_BUNDLE_V1 PART 1/Y only. No prose.\n"
            prompt += "FORMAT RULES:\n"
            prompt += "- First line must be: FD_BUNDLE_V1 PART 1/Y\n"
            prompt += "- Metadata lines must be key: value\n"
            prompt += "- File blocks must be: FILE: path (with colon) then <<< then content then >>>\n"
            prompt += "- Close every FILE block with >>>\n"
            prompt += "- Do NOT output markdown fences\n"
            prompt += "You MUST include an updated snapshot file: docs/assets/app/app-source_<timestamp>.txt\n"
            prompt += "\nWORKFLOW_LOGS\n" + logs_text[:200000] + "\n"
            _write(artifacts / ("fix_prompt_attempt_" + str(attempt) + ".txt"), prompt)

            patch, parts, perr = _get_fix_bundle_and_parse(prompt, artifacts / ("fix_bundle_attempt_" + str(attempt)), max_tries=3)
            if patch is None:
                _write(artifacts / ("fix_parse_failed_attempt_" + str(attempt) + ".txt"), perr + "\n")
                continue

            apply_patch(patch, str(wt_dir))

            # Apply returned snapshot (slice into files)
            snap_dir = wt_dir / "docs" / "assets" / "app"
            snaps = sorted([str(p) for p in snap_dir.glob("app-source_*.txt")]) if snap_dir.exists() else []
            if snaps:
                newest = snaps[-1]
                txt = Path(newest).read_text(encoding="utf-8", errors="ignore")
                apply_snapshot(txt, wt_dir)

            subprocess.check_call(["git","add","-A"], cwd=str(wt_dir))
            st = _run(["git","status","--porcelain"], str(wt_dir))
            _write(artifacts / ("git_status_attempt_" + str(attempt) + ".txt"), st.stdout)

            try:
                subprocess.check_call(["git","commit","-m","FD tune attempt " + str(attempt)], cwd=str(wt_dir))
            except Exception:
                pass
            pushr = _run(["git","push","--force-with-lease"], str(wt_dir))
            _write(artifacts / ("git_push_attempt_" + str(attempt) + ".txt"), pushr.stdout)
            if pushr.returncode != 0:
                raise RuntimeError("FD_FAIL: git push failed")

        except Exception:
            _write(artifacts / ("unexpected_exception_attempt_" + str(attempt) + ".txt"), traceback.format_exc() + "\n")
            continue

    print("FD_FAIL: tuning attempts exhausted")
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
