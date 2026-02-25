#!/usr/bin/env python3
import os
import re
import sys
import tempfile
import shutil
import datetime
from pathlib import Path
from typing import Dict

from src.github_api import get_issue, create_comment, close_issue
from src.gemini_client import call_gemini
from src.fd_manifest import load_manifest_from_text, extract_manifest_json
from src.fd_apply import apply_manifest
from src.fd_release import gh_release_create
from src.role_config import get_model_for_role, get_endpoint_base

def die(msg: str) -> None:
    sys.stdout.write(msg + "\n")
    raise SystemExit(1)

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def _field(body: str, key: str) -> str:
    m = re.search(r"^" + re.escape(key) + r"\s*(.+?)\s*$", body, re.M)
    return m.group(1).strip() if m else ""

def _ms_id(body: str) -> str:
    ms = _field(body, "Milestone ID:")
    return ms if ms != "" else "MS-UNKNOWN"

def _work_branch(ms_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "-", ms_id)
    return "work/" + safe

def _role_name_from_guide(role_guide_file: str) -> str:
    # Example: ROLE_BE.txt -> Backend Engineer (BE)
    base = os.path.basename(role_guide_file).upper()
    if base == "ROLE_BE.TXT":
        return "Backend Engineer (BE)"
    if base == "ROLE_FE.TXT":
        return "Frontend Engineer (FE)"
    if base == "ROLE_REVIEWER.TXT":
        return "Code Reviewer"
    if base == "ROLE_QA.TXT":
        return "QA Lead"
    if base == "ROLE_TECH_LEAD.TXT":
        return "Tech Lead (Architecture / Delivery Lead)"
    if base == "ROLE_PM.TXT":
        return "Product Manager (PM)"
    if base == "ROLE_DEVOPS.TXT":
        return "DevOps / Platform Engineer"
    if base == "ROLE_TECH_WRITER.TXT":
        return "Technical Writer"
    return "Unknown"

def main() -> int:
    if len(sys.argv) != 3:
        sys.stdout.write("usage: run_wi_issue.py <ISSUE_NUMBER> <ROLE_GUIDE_FILE>\n")
        return 2

    issue_number = int(sys.argv[1])
    role_guide_file = sys.argv[2]

    gh_token = os.environ.get("GITHUB_TOKEN", "")
    if gh_token == "":
        die("FD_FAIL: missing GITHUB_TOKEN")
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if api_key == "":
        die("FD_FAIL: missing GEMINI_API_KEY")

    issue = get_issue(issue_number, gh_token)
    title = str(issue.get("title") or "")
    body = str(issue.get("body") or "")
    ms_id = _ms_id(body)

    guides_dir = Path("agent_guides")
    global_txt = _read(guides_dir / "GLOBAL_CONSTRAINTS.txt")
    output_mode = _read(guides_dir / "OUTPUT_MODE.txt")
    role_txt = _read(guides_dir / role_guide_file)

    prompt = global_txt + "\n\n" + output_mode + "\n\n" + role_txt + "\n\n" + "INPUT_ISSUE_TITLE\n" + title + "\n\n" + "INPUT_ISSUE_BODY\n" + body + "\n"

    role_name = _role_name_from_guide(role_guide_file)
    model = get_model_for_role(role_name)
    endpoint_base = get_endpoint_base()

    out_text = call_gemini(api_key, prompt, timeout_s=240, model=model, endpoint_base=endpoint_base)
    if out_text.strip() == "":
        die("FD_FAIL: model returned empty output role=" + role_name + " model=" + model)

    manifest = load_manifest_from_text(out_text)
    if manifest.work_item_id == "":
        # best effort: infer from issue body
        wid = _field(body, "Work Item ID:")
        if wid != "":
            manifest.work_item_id = wid

    tmp = tempfile.mkdtemp()
    try:
        # Build work branch staging content from pipeline_base only.
        staging = os.path.join(tmp, "staging")
        os.makedirs(staging, exist_ok=True)
        base = Path("pipeline_base")
        if not base.exists():
            die("FD_FAIL: missing pipeline_base")
        shutil.copytree(str(base), staging, dirs_exist_ok=True)

        apply_manifest(manifest, staging)

        # Package staging as artifact.zip
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(assets_dir, exist_ok=True)
        artifact_zip = os.path.join(assets_dir, "artifact.zip")
        from src.fd_zip import zip_dir
        zip_dir(staging, artifact_zip)

        manifest_path = os.path.join(assets_dir, "manifest.json")
        Path(manifest_path).write_text(extract_manifest_json(out_text) + "\n", encoding="utf-8")

        ver_path = os.path.join(assets_dir, "verification_report.txt")
        Path(ver_path).write_text("FD_VERIFICATION\nISSUE=" + str(issue_number) + "\nMODEL=" + model + "\n", encoding="utf-8")

        tag = "FD-" + (manifest.work_item_id or ("WI-" + str(issue_number))) + "-" + role_name.replace(" ", "_") + "-" + datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        create_release_with_assets(tag, "FD WI execution", [(artifact_zip, "artifact.zip"), (manifest_path, "manifest.json"), (ver_path, "verification_report.txt")])

        create_comment(issue_number, "FD_WI_DONE\nRELEASE=" + tag + "\n", gh_token)
        close_issue(issue_number, gh_token)

        sys.stdout.write("FD_OK: release_tag=" + tag + "\n")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    raise SystemExit(main())
