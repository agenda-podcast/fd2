#!/usr/bin/env python3
import os
import shutil
import sys
import tempfile
import datetime
from pathlib import Path

sys.dont_write_bytecode = True

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.fd_prompt import build_prompt
from src.gemini_client import call_gemini
from src.role_config import load_role_model_map, model_for_role, endpoint_base
from src.fd_manifest import load_manifest_from_text
from src.fd_apply import apply_manifest
from src.fd_zip import zip_dir
from src.fd_release import write_text, write_json, gh_release_create
from src.wi_queue import pick_next_wi_issue_number
from src.github_api import get_issue, create_comment, close_issue, dispatch_workflow
from tools.check_ascii import run as check_ascii_run
from tools.check_line_limits import run as check_lines_run
from tools.check_no_ellipses import run as check_ellipses_run

def die(msg: str, code: int = 2) -> int:
    print(msg)
    return code

def _extract_field(text: str, key: str) -> str:
    for line in text.splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return ""

def _task_key(task_num: str):
    if task_num.strip() == "":
        return (999, [])
    parts = []
    for p in task_num.split("."):
        p = p.strip()
        if p == "":
            continue
        try:
            parts.append(int(p))
        except Exception:
            parts.append(999)
    return (len(parts), parts)



def main() -> int:
    if len(sys.argv) < 2:
        return die("FD_FAIL: missing issue_number")
    issue_number = int(sys.argv[1])
    role_guide_override = sys.argv[2] if len(sys.argv) > 2 else ""

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if api_key == "":
        return die("FD_FAIL: missing GEMINI_API_KEY")
    token = os.environ.get("FD_BOT_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
    if token == "":
        return die("FD_FAIL: missing GITHUB_TOKEN")

    issue = get_issue(issue_number, token)
    title = str(issue.get("title") or "")
    body = str(issue.get("body") or "")

    role_guide = role_guide_override.strip() or role_guide_for_issue_body(body)
    role_map = load_role_model_map()
    role = _extract_field(body, "Receiver Role (Next step)") or "Engineer"
    model = model_for_role(role_map, role)
    base = endpoint_base(role_map)

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if run_policy_checks(repo_root) != 0:
        return 1

    prompt = build_prompt(repo_root, body, role_guide)
    out_text = call_gemini(api_key, prompt, model=model, endpoint_base=base, timeout_s=240)
    if out_text.strip() == "":
        return die("FD_FAIL: model returned empty output", 1)

    manifest = load_manifest_from_text(out_text)

    stage = Path(tempfile.mkdtemp(prefix="fd_wi_stage_"))
    # Use pipeline_base if exists, else empty stage
    pipeline_base = Path(repo_root) / "pipeline_base"
    if pipeline_base.exists():
        shutil.copytree(pipeline_base, stage, dirs_exist_ok=True)

    apply_manifest(manifest, stage)

    # Build artifact
    artifacts_dir = Path(tempfile.mkdtemp(prefix="fd_wi_artifacts_"))
    artifact_zip = artifacts_dir / "artifact.zip"
    zip_dir(stage, artifact_zip)

    now = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    wi_id = _extract_field(body, "Work Item ID") or ("WI-" + str(issue_number))
    rel_tag = "FD-" + wi_id + "-" + now

    manifest_path = artifacts_dir / "manifest.json"
    write_json(manifest_path, manifest)
    log_path = artifacts_dir / "runner_log.txt"
    write_text(log_path, "WI issue_number=" + str(issue_number) + "\nrole_guide=" + role_guide + "\nmodel=" + model + "\n")
    report_path = artifacts_dir / "verification_report.txt"
    write_text(report_path, "FD_WI_EXECUTED\nWI=" + wi_id + "\nISSUE=" + str(issue_number) + "\n")

    gh_release_create(rel_tag, "WI " + wi_id, [artifact_zip, manifest_path, log_path, report_path])

    create_comment(issue_number, "FD_WI_DONE\nRELEASE=" + rel_tag, token)
    close_issue(issue_number, token)

    # Dispatch next WI if possible (needs FD_BOT_TOKEN to avoid recursion limits)
    if os.environ.get("FD_BOT_TOKEN", "") != "":
        next_issue = pick_next_wi_issue_number(token)
        if next_issue != 0:
            dispatch_workflow("orchestrate_wi_issue.yml", "main", {"issue_number": str(next_issue), "role_guide": ""}, token)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
