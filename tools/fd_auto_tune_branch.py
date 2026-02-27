#!/usr/bin/env python3
import datetime
import sys

import os
import subprocess
import tempfile
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
        prompt = ""
        prompt += "ROLE: BUILDER\n"
        prompt += "TASK: Fix the application to make dry-run and unit tests pass.\n"
        prompt += "OUTPUT: FD_BUNDLE_V1 PART 1/Y only. No prose. Close every FILE block.\n"
        prompt += "CONTEXT: failing logs follow.\n\n" + failing + "\n"
        _write(artifacts / ("fix_prompt_attempt_" + str(attempt) + ".txt"), prompt)
        parts = _call_bundle(prompt, artifacts / ("fix_bundle_attempt_" + str(attempt)))
        patch = parse_bundle_parts(parts)
        apply_patch(patch, repo_root)

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
