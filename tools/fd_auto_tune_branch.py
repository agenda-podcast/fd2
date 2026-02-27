#!/usr/bin/env python3
import datetime
import sys

import os
import subprocess
import tempfile
import traceback
import glob
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.getcwd()))

from src.fd_auto.gemini_client import call_gemini
from src.fd_auto.patch_parse import parse_bundle_parts, bundle_total_parts
from src.fd_auto.apply_patch import apply_patch
from src.fd_auto.util import first_n_lines

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
            # Save the raw output for inspection
            try:
                (out_dir / ("parse_error_try_" + str(k) + ".txt")).write_text(last_err + "\n", encoding="utf-8", errors="ignore")
            except Exception:
                pass
            continue
    return (None, [], last_err)

def _upload_snapshot_chunks(snapshot_text: str, workflow_name: str, out_dir: Path) -> None:
    # Multi-call upload so the model can see full repo context without exceeding request size limits.
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
        # Upload snapshot to the model in multiple calls (ACK-only) to provide full context.
        _upload_snapshot_chunks(snapshot_text, workflow_name, artifacts / ("snapshot_upload_attempt_" + str(attempt)))
        prompt = ""
        prompt += "ROLE: BUILDER\n"
        prompt += "TASK: Receive repository snapshot chunk. Do not propose fixes yet.\n"
        prompt += "WORKFLOW_NAME: " + workflow_name + "\n"
        prompt += "INSTRUCTION: Reply with exactly: ACK " + str(i+1) + "/" + str(total) + "\n"
        prompt += "SNAPSHOT_CHUNK " + str(i+1) + "/" + str(total) + "\n"
        prompt += chunk + "\n"
        (out_dir / ("snapshot_chunk_" + str(i+1) + "_prompt.txt")).write_text(prompt, encoding="utf-8", errors="ignore")
        resp = call_gemini(prompt, timeout_s=900)
        (out_dir / ("snapshot_chunk_" + str(i+1) + "_response.txt")).write_text(resp, encoding="utf-8", errors="ignore")

def main() -> int:
    import sys
    if len(sys.argv) < 4:
        print("usage: fd_auto_tune_branch.py <branch> <workflow_name> <max_attempts>")
        return 2
    branch = sys.argv[1].strip()
    workflow_name = sys.argv[2].strip() or "dry_run_and_unittest"
    max_attempts_arg = int((sys.argv[3].strip() or "3"))
    if branch == "":
        return 2

    repo_root = os.getcwd()
    max_attempts = max_attempts_arg
    if max_attempts < 1:
        max_attempts = 1
    print("FD_DEBUG: tune_config branch=" + branch + " workflow_name=" + workflow_name + " max_attempts=" + str(max_attempts))

    artifacts = Path(tempfile.mkdtemp(prefix="fd_tune_artifacts_"))
    _write(artifacts / "branch.txt", branch + "\n")

    subprocess.check_call(["git","checkout",branch])

    for attempt in range(1, max_attempts + 1):
        print("FD_DEBUG: attempt_begin " + str(attempt) + "/" + str(max_attempts))
        # Never crash the workflow; record errors and continue.
        try:
            # Install deps if requirements present
            if Path("requirements.txt").exists():
                _run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], repo_root)

            dry = None
            tests = None
            if workflow_name == "dry_run_only":
                dry = _run(["python", "src/main.py", "--dry-run"], repo_root)
                _write(artifacts / ("dry_run_attempt_" + str(attempt) + ".log"), dry.stdout)
                ok = (dry.returncode == 0)
            elif workflow_name == "unittest_only":
                tests = _run(["python", "-m", "unittest", "discover", "-s", "tests"], repo_root)
                _write(artifacts / ("tests_attempt_" + str(attempt) + ".log"), tests.stdout)
                ok = (tests.returncode == 0)
            else:
                dry = _run(["python", "src/main.py", "--dry-run"], repo_root)
                _write(artifacts / ("dry_run_attempt_" + str(attempt) + ".log"), dry.stdout)
                tests = _run(["python", "-m", "unittest", "discover", "-s", "tests"], repo_root)
                _write(artifacts / ("tests_attempt_" + str(attempt) + ".log"), tests.stdout)
                ok = (dry.returncode == 0 and tests.returncode == 0)

            if ok:
                print("FD_OK: green")
                print("FD_DEBUG: attempt_success " + str(attempt))
                return 0

            dry_rc = str(dry.returncode) if dry is not None else "NA"
            dry_out = first_n_lines(dry.stdout, 200) if dry is not None else ""
            test_rc = str(tests.returncode) if tests is not None else "NA"
            test_out = first_n_lines(tests.stdout, 200) if tests is not None else ""
            failing = "WORKFLOW_NAME=" + workflow_name + "\nDRY_RUN_RC=" + dry_rc + "\n" + dry_out + "\n\nTEST_RC=" + test_rc + "\n" + test_out

            snap_dir = os.path.join(repo_root, "docs", "assets", "app")
            snaps = sorted(glob.glob(os.path.join(snap_dir, "app-source_*.txt")))
            snapshot_path = snaps[-1] if snaps else ""
            snapshot_text = ""
            if snapshot_path:
                snapshot_text = open(snapshot_path, "r", encoding="utf-8", errors="ignore").read()

            # Upload full snapshot in multiple calls (ACK-only) so the model sees full context.
            _upload_snapshot_chunks(snapshot_text, workflow_name, artifacts / ("snapshot_upload_attempt_" + str(attempt)))

            prompt = ""
            prompt += "ROLE: BUILDER\n"
            prompt += "TASK: Fix the application to make the selected workflow pass.\n"
            prompt += "WORKFLOW_NAME=" + workflow_name + "\n"
            prompt += "OUTPUT: FD_BUNDLE_V1 PART 1/Y only. No prose.\n"
            prompt += "FORMAT RULES:\n"
            prompt += "- First line must be: FD_BUNDLE_V1 PART 1/Y\n"
            prompt += "- Metadata lines must be key: value\n"
            prompt += "- File blocks must be: FILE: path (with colon) then <<< then content then >>>\n"
            prompt += "- Close every FILE block with >>>\n"
            prompt += "- Do NOT output markdown fences\n"
            prompt += "You MUST include an updated snapshot file: docs/assets/app/app-source_<timestamp>.txt\n"
            prompt += "\nFAIL_LOGS\n" + failing + "\n"

            _write(artifacts / ("fix_prompt_attempt_" + str(attempt) + ".txt"), prompt)

            patch, parts, perr = _get_fix_bundle_and_parse(prompt, artifacts / ("fix_bundle_attempt_" + str(attempt)), max_tries=3)
            if patch is None:
                _write(artifacts / ("fix_parse_failed_attempt_" + str(attempt) + ".txt"), perr + "\n")
                print("FD_WARN: fix_parse_failed attempt=" + str(attempt))
                continue

            apply_patch(patch, repo_root)

            # If model returned a new snapshot file, apply it by slicing into real files.
            snaps2 = sorted(glob.glob(os.path.join(snap_dir, "app-source_*.txt")))
            if snaps2:
                newest = snaps2[-1]
                subprocess.check_call(["python3", "tools/fd_auto_apply_snapshot.py", newest], cwd=repo_root)

            subprocess.check_call(["git", "add", "-A"])
            try:
                subprocess.check_call(["git", "commit", "-m", "FD tune attempt " + str(attempt)])
            except Exception:
                pass
            subprocess.check_call(["git", "push", "--force-with-lease"])
        except Exception as exc:
            _write(artifacts / ("unexpected_exception_attempt_" + str(attempt) + ".txt"), traceback.format_exc() + "\n")
            # Attempt self-repair via Gemini using the exception traceback.
            try:
                snap_dir = os.path.join(repo_root, "docs", "assets", "app")
                snaps = sorted(glob.glob(os.path.join(snap_dir, "app-source_*.txt")))
                snapshot_path = snaps[-1] if snaps else ""
                snapshot_text = ""
                if snapshot_path:
                    snapshot_text = open(snapshot_path, "r", encoding="utf-8", errors="ignore").read()
                _upload_snapshot_chunks(snapshot_text, workflow_name, artifacts / ("snapshot_upload_exception_attempt_" + str(attempt)))
                repair = ""
                repair += "ROLE: BUILDER\n"
                repair += "TASK: Fix the repository so the tuning workflow and the selected app checks can run.\n"
                repair += "WORKFLOW_NAME=" + workflow_name + "\n"
                repair += "OUTPUT: FD_BUNDLE_V1 PART 1/Y only. No prose.\n"
                repair += "You MUST include an updated snapshot file: docs/assets/app/app-source_<timestamp>.txt\n"
                repair += "\nEXCEPTION_TRACEBACK\n" + first_n_lines(traceback.format_exc(), 400) + "\n"
                _write(artifacts / ("self_repair_prompt_attempt_" + str(attempt) + ".txt"), repair)
                patch2, parts2, perr2 = _get_fix_bundle_and_parse(repair, artifacts / ("self_repair_bundle_attempt_" + str(attempt)), max_tries=3)
                if patch2 is not None:
                    apply_patch(patch2, repo_root)
                    snaps3 = sorted(glob.glob(os.path.join(snap_dir, "app-source_*.txt")))
                    if snaps3:
                        newest3 = snaps3[-1]
                        subprocess.check_call(["python3", "tools/fd_auto_apply_snapshot.py", newest3], cwd=repo_root)
                    subprocess.check_call(["git", "add", "-A"])
                    try:
                        subprocess.check_call(["git", "commit", "-m", "FD self-repair attempt " + str(attempt)])
                    except Exception:
                        pass
                    subprocess.check_call(["git", "push", "--force-with-lease"])
            except Exception as exc2:
                _write(artifacts / ("self_repair_exception_attempt_" + str(attempt) + ".txt"), traceback.format_exc() + "\n")
            continue



    print("FD_FAIL: tuning attempts exhausted")
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
