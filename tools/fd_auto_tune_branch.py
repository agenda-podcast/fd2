#!/usr/bin/env python3
import glob
import io
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, os.path.abspath(os.getcwd()))

from src.fd_auto.actions_api import (
    dispatch_workflow,
    download_artifact_zip,
    download_run_logs_zip,
    extract_logs_text,
    find_latest_run_id,
    list_run_artifacts,
    wait_run_complete,
)
from src.fd_auto.gemini_client import call_gemini

def _preview(s: str, n: int = 600) -> str:
    t = (s or "").replace("\r\n","\n").replace("\r","\n")
    t = t.replace("\n", " ")
    if len(t) > n:
        return t[:n] + "..."
    return t

def _step(msg: str) -> None:
    print("FD_STEP: " + msg)

def _write(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8", errors="ignore")

def _run(cmd: List[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

def _parse_inputs(s: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
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

def _ensure_worktree(branch: str) -> tuple[Path, Path]:
    repo_root = Path(os.getcwd())
    wt_dir = Path(tempfile.mkdtemp(prefix="fd_tune_wt_"))
    subprocess.check_call(["git","fetch","origin",branch], cwd=str(repo_root))
    subprocess.check_call(["git","worktree","add",str(wt_dir),branch], cwd=str(repo_root))
    return wt_dir, repo_root

def _read_latest_snapshot(wt_dir: Path) -> str:
    snap_dir = wt_dir / "docs" / "assets" / "app"
    if not snap_dir.exists():
        return ""
    snaps = sorted([str(p) for p in snap_dir.glob("app-source_*.txt")])
    if not snaps:
        return ""
    return Path(snaps[-1]).read_text(encoding="utf-8", errors="ignore")

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
        prompt += "TASK: Receive repository snapshot chunk. Reply only with: ACK " + str(i+1) + "/" + str(total) + "\n"
        prompt += "SNAPSHOT_CHUNK " + str(i+1) + "/" + str(total) + "\n"
        prompt += chunk + "\n"
        _write(out_dir / ("snapshot_chunk_" + str(i+1) + "_prompt.txt"), prompt)
        resp = call_gemini(prompt, timeout_s=900)
        _write(out_dir / ("snapshot_chunk_" + str(i+1) + "_response.txt"), resp)

def _call_gemini_diff(prompt: str, artifacts: Path, label: str) -> str:
    _step("gemini_call_begin label=" + label + " prompt_chars=" + str(len(prompt)))
    _step("gemini_prompt_preview label=" + label + " text=" + _preview(prompt))
    _step("gemini_prompt_file label=" + label + " path=" + str(artifacts / (label + "_prompt.txt")) )
    _write(artifacts / (label + "_prompt.txt"), prompt)
    resp = call_gemini(prompt, timeout_s=900)
    _write(artifacts / (label + "_response.txt"), resp)
    _step("gemini_response_preview label=" + label + " text=" + _preview(resp))
    _step("gemini_response_file label=" + label + " path=" + str(artifacts / (label + "_response.txt")) )
    _step("gemini_call_end label=" + label + " resp_chars=" + str(len(resp)))
    return resp

def _call_gemini_bundle(prompt: str, artifacts: Path, label: str) -> str:
    _step("gemini_call_begin label=" + label + " prompt_chars=" + str(len(prompt)))
    _step("gemini_prompt_preview label=" + label + " text=" + _preview(prompt))
    _step("gemini_prompt_file label=" + label + " path=" + str(artifacts / (label + "_prompt.txt")) )
    _write(artifacts / (label + "_prompt.txt"), prompt)
    resp = call_gemini(prompt, timeout_s=900)
    _write(artifacts / (label + "_response.txt"), resp)
    _step("gemini_response_preview label=" + label + " text=" + _preview(resp))
    _step("gemini_response_file label=" + label + " path=" + str(artifacts / (label + "_response.txt")) )
    _step("gemini_call_end label=" + label + " resp_chars=" + str(len(resp)))
    return resp

def _apply_file_bundle(bundle_text: str, repo_dir: Path, artifacts: Path, label: str) -> bool:
    t = (bundle_text or "").replace("\r\n","\n").replace("\r","\n")
    ls = t.split("\n")
    i = 0
    wrote = 0
    while i < len(ls):
        line = ls[i].strip()
        if line.startswith("FILE:"):
            path = line.split(":",1)[1].strip()
            i += 1
            if i >= len(ls) or ls[i].strip() != "<<<":
                _write(artifacts / (label + "_bundle_parse_fail.txt"), "missing <<< for " + path + "\n")
                return False
            i += 1
            content = []
            while i < len(ls) and ls[i].strip() != ">>>":
                content.append(ls[i])
                i += 1
            if i >= len(ls):
                _write(artifacts / (label + "_bundle_parse_fail.txt"), "missing >>> for " + path + "\n")
                return False
            i += 1
            outp = repo_dir / path
            outp.parent.mkdir(parents=True, exist_ok=True)
            outp.write_text("\n".join(content) + "\n", encoding="utf-8", errors="ignore")
            wrote += 1
            continue
        i += 1
    _write(artifacts / (label + "_bundle_applied.txt"), "files_written=" + str(wrote) + "\n")
    return wrote > 0

def _extract_failed_paths(git_apply_log: str) -> List[str]:
    paths: List[str] = []
    for line in (git_apply_log or "").splitlines():
        if "patch failed:" in line:
            # error: patch failed: path:line
            try:
                part = line.split("patch failed:",1)[1].strip()
                p = part.split(":",1)[0].strip()
                if p and p not in paths:
                    paths.append(p)
            except Exception:
                pass
        if line.startswith("Checking patch "):
            p = line.replace("Checking patch ","").strip().strip(".")
            if p and p not in paths:
                paths.append(p)
    return paths[:5]

def _read_repo_file(repo_dir: Path, rel_path: str, max_chars: int = 8000) -> str:
    p = repo_dir / rel_path
    if not p.exists():
        return ""
    txt = p.read_text(encoding="utf-8", errors="ignore")
    if len(txt) > max_chars:
        return txt[:max_chars] + "\n"
    return txt

def _extract_diff(text: str) -> str:
    t = (text or "").replace("\r\n","\n").replace("\r","\n")
    idx = t.find("diff --git")
    if idx >= 0:
        d = t[idx:]
        if not d.endswith("\n"):
            d = d + "\n"
        return d
    # sometimes model returns '*** Begin Patch' - keep as fail if no diff.
    return ""

def main() -> int:
    if len(sys.argv) < 4:
        print("usage: fd_auto_tune_branch.py <branch> <workflow_file> <max_attempts> [workflow_inputs]")
        return 2
    branch = sys.argv[1].strip()
    workflow_file = sys.argv[2].strip()
    max_attempts = int((sys.argv[3].strip() or "5"))
    workflow_inputs = sys.argv[4] if len(sys.argv) > 4 else ""

    token = (os.environ.get("FD_BOT_TOKEN") or "").strip()
    actions_token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if token == "":
        raise RuntimeError("FD_FAIL: missing FD_BOT_TOKEN")
    if actions_token == "":
        raise RuntimeError("FD_FAIL: missing GITHUB_TOKEN")

    if max_attempts < 1:
        max_attempts = 1

    _step("tune_config branch=" + branch + " workflow_file=" + workflow_file + " max_attempts=" + str(max_attempts))

    artifacts = Path(tempfile.mkdtemp(prefix="fd_tune_artifacts_"))
    _write(artifacts / "branch.txt", branch + "\n")
    _write(artifacts / "workflow_file.txt", workflow_file + "\n")
    _write(artifacts / "workflow_inputs.txt", workflow_inputs + "\n")

    wt_dir, repo_root = _ensure_worktree(branch)
    _set_origin_with_token(repo_root, token)

    inputs = _parse_inputs(workflow_inputs)
    apply_err = ""
    diff_fail_count = 0
    apply_failed_context = ""
    apply_failed_context = ""

    for attempt in range(1, max_attempts + 1):
        _step("attempt_begin " + str(attempt) + "/" + str(max_attempts))
        try:
            # Dispatch target workflow
            start_epoch = time.time()
            _step("dispatch_workflow file=" + workflow_file + " ref=" + branch + " inputs=" + str(inputs))
            dispatch_workflow(workflow_file, branch, inputs, actions_token)

            run_id = find_latest_run_id(workflow_file, branch, start_epoch - 5, actions_token, timeout_s=180)
            _step("workflow_run_found run_id=" + str(run_id))
            run_info = wait_run_complete(run_id, actions_token, timeout_s=3600)
            status = str(run_info.get("status") or "")
            conclusion = str(run_info.get("conclusion") or "")
            html_url = str(run_info.get("html_url") or "")
            _step("workflow_run_completed run_id=" + str(run_id) + " status=" + status + " conclusion=" + conclusion)

            logs_zip = download_run_logs_zip(run_id, actions_token)
            logs_text = extract_logs_text(logs_zip, max_chars=350000)
            _write(artifacts / ("run_" + str(run_id) + "_attempt_" + str(attempt) + ".log"), logs_text)

            # Download run artifacts
            arts = list_run_artifacts(run_id, actions_token)
            _write(artifacts / ("run_" + str(run_id) + "_artifacts.json"), str(arts) + "\n")
            for a in arts:
                aid = int(a.get("id") or 0)
                name = str(a.get("name") or "artifact")
                if aid <= 0:
                    continue
                _step("download_artifact name=" + name + " id=" + str(aid))
                blob = download_artifact_zip(aid, actions_token)
                outp = artifacts / ("run_" + str(run_id) + "_artifact_" + name + ".zip")
                outp.write_bytes(blob)

            if status == "completed" and conclusion == "success":
                _step("green run_id=" + str(run_id))
                return 0

            # Prepare context: snapshot + logs + artifacts list
            snapshot_text = _read_latest_snapshot(wt_dir)
            _upload_snapshot_chunks(snapshot_text, artifacts / ("snapshot_upload_attempt_" + str(attempt)))

            prompt = ""
            prompt += "You are fixing a GitHub repo so that a workflow passes.\n"
            prompt += "Return ONLY a unified diff that `git apply` can apply. Start with: diff --git\n"
            prompt += "FIRST LINE MUST BE: diff --git a/FILE b/FILE\n"
            prompt += "REQUIREMENTS:\n"
            prompt += "- Use minimal hunks (like --unified=0). Avoid including blank context lines.\n"
            prompt += "- Hunk headers (@@ -a,b +c,d @@) must match the number of following +/-/space lines.\n"
            prompt += "- Do not include prose or markdown fences.\n"

            prompt += "Do not include markdown fences. Do not include explanations.\n"
            prompt += "\nTARGET\n"
            prompt += "branch: " + branch + "\n"
            prompt += "workflow_file: " + workflow_file + "\n"
            if html_url:
                prompt += "run_url: " + html_url + "\n"
            prompt += "status: " + status + "\n"
            prompt += "conclusion: " + conclusion + "\n"
            prompt += "\nWORKFLOW_LOGS\n"
            prompt += logs_text[:300000] + "\n"
            if apply_err.strip() != "":
                prompt += "\nPREVIOUS_GIT_APPLY_ERROR\n" + apply_err + "\n"
            if apply_failed_context.strip() != "":
                prompt += "\nCURRENT_FILE_CONTEXT\n" + apply_failed_context[:120000] + "\n"
            prompt += "\nRUN_ARTIFACTS\n"
            prompt += str([str(x.get("name") or "") for x in arts]) + "\n"

            if diff_fail_count >= 2:
                bprompt = ""
                bprompt += "Return ONLY FILE bundle blocks. No prose.\n"
                bprompt += "FORMAT:\nFILE: path\n<<<\n<content>\n>>>\n\n"
                bprompt += "Change ONLY minimal files needed.\n"
                bprompt += "branch: " + branch + "\nworkflow_file: " + workflow_file + "\n"
                bprompt += "\nWORKFLOW_LOGS\n" + logs_text[:200000] + "\n"
                if apply_err.strip() != "":
                    bprompt += "\nPREVIOUS_GIT_APPLY_ERROR\n" + apply_err + "\n"
                if apply_failed_context.strip() != "":
                    bprompt += "\nCURRENT_FILE_CONTEXT\n" + apply_failed_context[:120000] + "\n"
                bundle_text = _call_gemini_bundle(bprompt, artifacts, "bundle_attempt_" + str(attempt))
                okb = _apply_file_bundle(bundle_text, Path(wt_dir), artifacts, "bundle_attempt_" + str(attempt))
                if not okb:
                    _step("bundle_apply_failed attempt=" + str(attempt))
                    diff_fail_count += 1
                    continue
                _step("bundle_apply_ok attempt=" + str(attempt))
                subprocess.check_call(["git","add","-A"], cwd=str(wt_dir))
                try:
                    subprocess.check_call(["git","commit","-m","FD tune bundle attempt " + str(attempt)], cwd=str(wt_dir))
                except Exception:
                    pass
                pushb = _run(["git","push","--force-with-lease"], str(wt_dir))
                _write(artifacts / ("git_push_bundle_attempt_" + str(attempt) + ".log"), pushb.stdout)
                if pushb.returncode != 0:
                    _step("git_push_failed attempt=" + str(attempt))
                    continue
                _step("git_push_ok attempt=" + str(attempt))
                diff_fail_count = 0
                apply_err = ""
                apply_failed_context = ""
                continue

            diff_text = _call_gemini_diff(prompt, artifacts, "fix_attempt_" + str(attempt))
            diff = _extract_diff(diff_text)
            if diff.strip() == "":
                _write(artifacts / ("fix_diff_missing_attempt_" + str(attempt) + ".txt"), diff_text[:8000] + "\n")
                _step("diff_missing attempt=" + str(attempt))
                diff_fail_count += 1
                # Fallback: request FILE bundle immediately when diff is missing.
                bprompt = ""
                bprompt += "Return ONLY FILE bundle blocks. No prose.\n"
                bprompt += "FORMAT:\nFILE: path\n<<<\n<content>\n>>>\n\n"
                bprompt += "Change ONLY minimal files needed.\n"
                bprompt += "branch: " + branch + "\nworkflow_file: " + workflow_file + "\n"
                bprompt += "\nWORKFLOW_LOGS\n" + logs_text[:200000] + "\n"
                if apply_err.strip() != "":
                    bprompt += "\nPREVIOUS_GIT_APPLY_ERROR\n" + apply_err + "\n"
                if apply_failed_context.strip() != "":
                    bprompt += "\nCURRENT_FILE_CONTEXT\n" + apply_failed_context[:120000] + "\n"
                bundle_text = _call_gemini_bundle(bprompt, artifacts, "bundle_after_diff_missing_" + str(attempt))
                okb = _apply_file_bundle(bundle_text, Path(wt_dir), artifacts, "bundle_after_diff_missing_" + str(attempt))
                if okb:
                    _step("bundle_apply_ok attempt=" + str(attempt))
                    subprocess.check_call(["git","add","-A"], cwd=str(wt_dir))
                    try:
                        subprocess.check_call(["git","commit","-m","FD tune bundle attempt " + str(attempt)], cwd=str(wt_dir))
                    except Exception:
                        pass
                    pushb = _run(["git","push","--force-with-lease"], str(wt_dir))
                    _write(artifacts / ("git_push_bundle_attempt_" + str(attempt) + ".log"), pushb.stdout)
                    if pushb.returncode == 0:
                        _step("git_push_ok attempt=" + str(attempt))
                        diff_fail_count = 0
                        apply_err = ""
                        apply_failed_context = ""
                        continue
                continue

            diff_path = artifacts / ("fix_attempt_" + str(attempt) + ".diff")
            if not diff.endswith("\n"):
                diff = diff + "\n"
            _write(diff_path, diff)

            # Apply diff in worktree
            app = _run(["git","apply","--3way","--whitespace=nowarn", str(diff_path)], str(wt_dir))
            _write(artifacts / ("git_apply_attempt_" + str(attempt) + ".log"), app.stdout)
            if app.returncode != 0:
                apply_err = app.stdout[:4000]
                paths = _extract_failed_paths(app.stdout)
                ctx_parts = []
                for p in paths:
                    ctx_parts.append("FILE_CURRENT_BEGIN " + p + "\n" + _read_repo_file(Path(wt_dir), p) + "FILE_CURRENT_END " + p + "\n")
                apply_failed_context = "\n".join(ctx_parts)
                _write(artifacts / ("git_apply_failed_context_attempt_" + str(attempt) + ".txt"), apply_failed_context)
                _step("git_apply_failed attempt=" + str(attempt))
                diff_fail_count += 1
                continue
            _step("git_apply_ok attempt=" + str(attempt))
            diff_fail_count = 0

            subprocess.check_call(["git","add","-A"], cwd=str(wt_dir))
            try:
                subprocess.check_call(["git","commit","-m","FD tune attempt " + str(attempt)], cwd=str(wt_dir))
            except Exception:
                pass
            push = _run(["git","push","--force-with-lease"], str(wt_dir))
            _write(artifacts / ("git_push_attempt_" + str(attempt) + ".log"), push.stdout)
            if push.returncode != 0:
                _step("git_push_failed attempt=" + str(attempt))
                continue
            _step("git_push_ok attempt=" + str(attempt))
            apply_err = ""
            apply_failed_context = ""
        except Exception:
            _write(artifacts / ("unexpected_exception_attempt_" + str(attempt) + ".txt"), traceback.format_exc() + "\n")
            _step("attempt_exception attempt=" + str(attempt))
            print(traceback.format_exc())
            continue

    _step("tuning_attempts_exhausted")
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
