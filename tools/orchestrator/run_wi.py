#!/usr/bin/env python3
import os
import sys
import tempfile
import datetime
from pathlib import Path

sys.dont_write_bytecode = True

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.fd_prompt import build_prompt
from src.gemini_client import call_gemini
from src.role_config import load_role_model_map, role_from_guide_filename, model_for_role, endpoint_base
from src.fd_manifest import load_manifest_from_text
from src.fd_apply import apply_manifest
from src.fd_zip import zip_dir
from src.fd_release import write_text, write_json, gh_release_create
from src.github_api import get_issue
from tools.check_ascii import run as check_ascii_run
from tools.check_line_limits import run as check_lines_run
from tools.check_no_ellipses import run as check_ellipses_run

def die(msg: str) -> None:
    sys.stdout.write(msg + "\n")
    raise SystemExit(1)

def run_policy_checks(root: str) -> None:
    # Remove python bytecode before checks
    for p in Path(root).rglob("__pycache__"):
        if p.is_dir():
            for child in p.rglob("*"):
                try:
                    child.unlink()
                except Exception:
                    pass
            try:
                p.rmdir()
            except Exception:
                pass
    for p in Path(root).rglob("*.pyc"):
        try:
            p.unlink()
        except Exception:
            pass

    if check_ascii_run(root) != 0:
        die("FD_FAIL: policy ascii")
    if check_lines_run(root) != 0:
        die("FD_FAIL: policy line-limits")
    if check_ellipses_run(root) != 0:
        die("FD_FAIL: policy no-ellipses")

def parse_producer_role(issue_body: str) -> str:
    for line in issue_body.splitlines():
        if line.strip().lower().startswith("owner role (producer):"):
            return line.split(":", 1)[1].strip()
    return ""

def role_to_guide(role: str) -> str:
    m = {
        "Product Manager (PM)": "ROLE_PM.txt",
        "Product Manager": "ROLE_PM.txt",
        "Tech Lead (Architecture / Delivery Lead)": "ROLE_TECH_LEAD.txt",
        "Frontend Engineer (FE)": "ROLE_FE.txt",
        "Backend Engineer (BE)": "ROLE_BE.txt",
        "DevOps / Platform Engineer": "ROLE_DEVOPS.txt",
        "Code Reviewer": "ROLE_REVIEWER.txt",
        "QA Lead": "ROLE_QA.txt",
        "Technical Writer": "ROLE_TECH_WRITER.txt",
    }
    if role in m:
        return m[role]
    return ""

def default_artifact_type_for_role(role: str) -> str:
    # Only implementers/reviewer default to pipeline snapshots.
    if role in ["Frontend Engineer (FE)", "Backend Engineer (BE)", "DevOps / Platform Engineer", "Code Reviewer"]:
        return "pipeline_snapshot"
    return "repo_patch"

def main() -> int:
    if len(sys.argv) < 2:
        sys.stdout.write("usage: run_wi.py <issue_number> [ROLE_*.txt] [artifact_type]\n")
        return 2

    issue_number = int(sys.argv[1])
    override_role_guide = sys.argv[2] if len(sys.argv) >= 3 else ""
    override_artifact_type = sys.argv[3] if len(sys.argv) >= 4 else ""

    token = os.environ.get("GITHUB_TOKEN", os.environ.get("GH_TOKEN", ""))
    if token == "":
        die("FD_FAIL: missing GITHUB_TOKEN")

    issue = get_issue(issue_number, token)
    title = issue.get("title", "")
    body = issue.get("body", "") or ""

    producer_role = parse_producer_role(body)
    if producer_role == "" and override_role_guide == "":
        die("FD_FAIL: cannot determine producer role from issue body and no role guide override provided")

    role_guide_file = override_role_guide
    if role_guide_file == "":
        role_guide_file = role_to_guide(producer_role)
        if role_guide_file == "":
            die("FD_FAIL: unsupported producer role for auto guide mapping role=" + producer_role)

    artifact_type = override_artifact_type if override_artifact_type != "" else default_artifact_type_for_role(producer_role)

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if api_key == "":
        die("FD_FAIL: missing GEMINI_API_KEY")

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    guides_dir = os.path.join(repo_root, "agent_guides")
    global_constraints = os.path.join(guides_dir, "GLOBAL_CONSTRAINTS.txt")
    output_mode = os.path.join(guides_dir, "OUTPUT_MODE.txt")
    role_guide_path = os.path.join(guides_dir, role_guide_file)

    role_model_map = load_role_model_map(os.path.join(guides_dir, "ROLE_MODEL_MAP.json"))
    role_name = role_from_guide_filename(role_guide_file)
    model = model_for_role(role_model_map, role_name)

    prompt = build_prompt(global_constraints, output_mode, role_guide_path, title, body, artifact_type)

    out_text = call_gemini(api_key, prompt, timeout_s=240, model=model, endpoint_base=endpoint_base())

    if out_text.strip() == "":
        die("FD_FAIL: model returned empty output role=" + role_name + " model=" + model)

    manifest = load_manifest_from_text(out_text)

    ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    tag = "FD-WI-" + str(issue_number) + "-" + role_name.replace(" ", "").upper() + "-" + ts

    with tempfile.TemporaryDirectory() as tmp:
        stage = os.path.join(tmp, "stage")
        os.makedirs(stage, exist_ok=True)

        apply_manifest(manifest, stage)
        run_policy_checks(stage)

        artifact_zip = os.path.join(tmp, "artifact.zip")
        zip_dir(stage, artifact_zip)

        manifest_path = os.path.join(tmp, "manifest.json")
        write_json(manifest_path, {
            "schema_version": manifest.schema_version,
            "work_item_id": manifest.work_item_id,
            "producer_role": manifest.producer_role,
            "artifact_type": manifest.artifact_type,
            "entry_point": manifest.entry_point,
            "build_command": manifest.build_command,
            "test_command": manifest.test_command,
            "verification_steps": manifest.verification_steps,
            "notes": manifest.notes,
            "files": [
                {"path": f.path, "content_type": f.content_type, "encoding": f.encoding}
                for f in manifest.files
            ],
            "delete": manifest.delete
        })

        verification_path = os.path.join(tmp, "verification_report.txt")
        write_text(verification_path, "\n".join(manifest.verification_steps))

        # Publish release with artifact + manifest + report
        gh_release_create(tag, [artifact_zip, manifest_path, verification_path])

        sys.stdout.write("FD_OK: release=" + tag + "\n")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
