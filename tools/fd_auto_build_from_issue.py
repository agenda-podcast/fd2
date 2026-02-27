#!/usr/bin/env python3
import datetime
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from src.fd_auto.github_api import get_issue, create_comment
from src.fd_auto.util import require_env, extract_field, slugify
from src.fd_auto.gemini_client import call_gemini
from src.fd_auto.patch_parse import parse_fd_patch_v1, parse_bundle_parts, bundle_total_parts
from src.fd_auto.apply_patch import apply_patch

def _write(path: Path, s: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(s, encoding="utf-8", errors="ignore")

def _call_bundle(prompt: str, out_dir: Path) -> list[str]:
    parts = []
    first = call_gemini(prompt, timeout_s=900)
    parts.append(first)
    _write(out_dir / "part_1.txt", first)
    x, y = bundle_total_parts(first)
    if y <= 1:
        return parts
    cur = x
    # hard cap; user can tune later
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
    if len(sys.argv) < 2:
        print("usage: fd_auto_build_from_issue.py <milestone_issue_number>")
        return 2
    issue_number = int(sys.argv[1])

    token = require_env("FD_BOT_TOKEN")
    repo_root = os.getcwd()

    issue = get_issue(issue_number, token)
    body = (issue.get("body") or "")
    title = (issue.get("title") or "")
    ms_id = extract_field(body, "Milestone ID") or "MS-01"
    app_slug = slugify(title)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    branch = "app-" + ms_id.lower() + "-" + ts

    artifacts = Path(tempfile.mkdtemp(prefix="fd_build_artifacts_"))
    _write(artifacts / "milestone_issue.txt", body)

    # 1) Plan (PM): FD_PATCH_V1 handoff-only
    pm_prompt = open("agent_guides/ROLE_PM.txt","r",encoding="utf-8",errors="ignore").read() if os.path.exists("agent_guides/ROLE_PM.txt") else "ROLE: PM\nOutput FD_PATCH_V1 with handoff files only.\n"
    plan_prompt = pm_prompt + "\n\nMILESTONE_TITLE\n" + title + "\n\nMILESTONE_BODY\n" + body + "\n"
    _write(artifacts / "plan_prompt.txt", plan_prompt)

    plan_out = ""
    patch = None
    last_err = ""
    for attempt in range(1,4):
        plan_out = call_gemini(plan_prompt, timeout_s=900)
        _write(artifacts / ("plan_output_attempt_" + str(attempt) + ".txt"), plan_out)
        try:
            patch = parse_fd_patch_v1(plan_out)
            break
        except Exception as exc:
            last_err = str(exc)
            continue
    if patch is None:
        create_comment(issue_number, "FD_FAIL: plan parse failed\nERROR=" + last_err, token)
        return 1

    # Apply plan into repo (handoff)
    apply_patch(patch, repo_root)

    # 2) Code bundle
    plan_text = ""
    plan_path = Path(repo_root) / "handoff" / "app_building_plan.md"
    if plan_path.exists():
        plan_text = plan_path.read_text(encoding="utf-8", errors="ignore")
    code_prompt = open("agent_guides/ROLE_BUILDER.txt","r",encoding="utf-8",errors="ignore").read() if os.path.exists("agent_guides/ROLE_BUILDER.txt") else ""
    code_prompt += "\n\nTASK\nGenerate FULL APPLICATION CODE ONLY.\n"
    code_prompt += "\n\nAPP_BUILDING_PLAN\n" + plan_text + "\n"
    code_prompt += "\nRULES\n- Output FD_BUNDLE_V1 PART 1/Y\n- Close every FILE block with >>>\n"
    _write(artifacts / "code_prompt.txt", code_prompt)
    code_parts = _call_bundle(code_prompt, artifacts / "code_bundle")
    code_patch = parse_bundle_parts(code_parts)
    apply_patch(code_patch, repo_root)

    # 3) Docs bundle
    docs_prompt = open("agent_guides/ROLE_BUILDER.txt","r",encoding="utf-8",errors="ignore").read() if os.path.exists("agent_guides/ROLE_BUILDER.txt") else ""
    docs_prompt += "\n\nTASK\nGenerate COMPREHENSIVE DOCUMENTATION ONLY.\n"
    docs_prompt += "- Write README.md and docs/howto.md and docs/troubleshooting.md\n"
    docs_prompt += "\n\nAPP_BUILDING_PLAN\n" + plan_text + "\n"
    docs_prompt += "\nRULES\n- Output FD_BUNDLE_V1 PART 1/Y\n- Close every FILE block with >>>\n"
    _write(artifacts / "docs_prompt.txt", docs_prompt)
    docs_parts = _call_bundle(docs_prompt, artifacts / "docs_bundle")
    docs_patch = parse_bundle_parts(docs_parts)
    apply_patch(docs_patch, repo_root)

    # 4) Tests bundle
    tests_prompt = open("agent_guides/ROLE_BUILDER.txt","r",encoding="utf-8",errors="ignore").read() if os.path.exists("agent_guides/ROLE_BUILDER.txt") else ""
    tests_prompt += "\n\nTASK\nGenerate UNIT TESTS ONLY.\n"
    tests_prompt += "- Write tests/ files for src/ modules\n"
    tests_prompt += "- Ensure tests run with: python -m unittest discover -s tests\n"
    tests_prompt += "\n\nAPP_BUILDING_PLAN\n" + plan_text + "\n"
    tests_prompt += "\nRULES\n- Output FD_BUNDLE_V1 PART 1/Y\n- Close every FILE block with >>>\n"
    _write(artifacts / "tests_prompt.txt", tests_prompt)
    tests_parts = _call_bundle(tests_prompt, artifacts / "tests_bundle")
    tests_patch = parse_bundle_parts(tests_parts)
    apply_patch(tests_patch, repo_root)

# 3) (Optional) docs and tests are deferred; this build flow only creates app branch from code bundle.
    # Users run Tune flow to add docs/tests using branch input and extra env keys.

    # Publish branch
    subprocess.check_call(["git","checkout","-B", branch])
    subprocess.check_call(["git","add","-A"])
    try:
        subprocess.check_call(["git","commit","-m","FD build " + branch])
    except Exception:
        pass
    subprocess.check_call(["git","push","-u","origin", branch, "--force-with-lease"])

    create_comment(issue_number, "FD_OK: built app branch\nBRANCH=" + branch + "\nARTIFACTS_DIR=" + str(artifacts), token)
    print("FD_OK: branch=" + branch)
    print("FD_ARTIFACTS_DIR=" + str(artifacts))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
