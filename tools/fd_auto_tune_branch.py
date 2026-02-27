#!/usr/bin/env python3
import datetime
import sys

import os
import subprocess
import tempfile
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

    artifacts = Path(tempfile.mkdtemp(prefix="fd_tune_artifacts_"))
    _write(artifacts / "branch.txt", branch + "\n")

    subprocess.check_call(["git","checkout",branch])

    for attempt in range(1, max_attempts + 1):
    
        # Install deps if requirements present
        if Path("requirements.txt").exists():
            _run([sys.executable,"-m","pip","install","-r","requirements.txt"], repo_root)

        dry = None
        tests = None
        if workflow_name == "dry_run_only":
            dry = _run(["python","src/main.py","--dry-run"], repo_root)
            _write(artifacts / ("dry_run_attempt_" + str(attempt) + ".log"), dry.stdout)
            ok = (dry.returncode == 0)
        elif workflow_name == "unittest_only":
            tests = _run(["python","-m","unittest","discover","-s","tests"], repo_root)
            _write(artifacts / ("tests_attempt_" + str(attempt) + ".log"), tests.stdout)
            ok = (tests.returncode == 0)
        else:
            dry = _run(["python","src/main.py","--dry-run"], repo_root)
            _write(artifacts / ("dry_run_attempt_" + str(attempt) + ".log"), dry.stdout)
            tests = _run(["python","-m","unittest","discover","-s","tests"], repo_root)
            _write(artifacts / ("tests_attempt_" + str(attempt) + ".log"), tests.stdout)
            ok = (dry.returncode == 0 and tests.returncode == 0)

        if ok:
            print("FD_OK: green")
            return 0

        # Ask Gemini for patch
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
        max_chars = int(os.environ.get("FD_SNAPSHOT_MAX_CHARS","180000") or "180000")
        chunk_chars = int(os.environ.get("FD_SNAPSHOT_CHUNK_CHARS","50000") or "50000")
        snapshot_snip = snapshot_text[:max_chars]
        prompt = ""
        prompt += "ROLE: BUILDER\n"
        prompt += "TASK: Fix the application to make dry-run and unit tests pass.\n"
        prompt += "OUTPUT: FD_BUNDLE_V1 PART 1/Y only. No prose. Close every FILE block.\n"
        prompt += "You MUST include an updated full repository snapshot file at: docs/assets/app/app-source_<timestamp>.txt\n"
        prompt += "CONTEXT: failing logs follow.\n\n" + failing + "\n\n"

        _write(artifacts / ("fix_prompt_attempt_" + str(attempt) + ".txt"), prompt)
        parts = _call_bundle(prompt, artifacts / ("fix_bundle_attempt_" + str(attempt)))
        patch = parse_bundle_parts(parts)
        apply_patch(patch, repo_root)
        # If the model returned a new snapshot file, apply it by slicing into real files.
        snap_dir2 = os.path.join(repo_root, "docs", "assets", "app")
        snaps2 = sorted(glob.glob(os.path.join(snap_dir2, "app-source_*.txt")))
        if snaps2:
            newest = snaps2[-1]
            subprocess.check_call(["python3","tools/fd_auto_apply_snapshot.py", newest], cwd=repo_root)

        subprocess.check_call(["git","add","-A"])
        try:
            subprocess.check_call(["git","commit","-m","FD tune attempt " + str(attempt)])
        except Exception:
            pass
        subprocess.check_call(["git","push","--force-with-lease"])
    print("FD_FAIL: tuning attempts exhausted")
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
