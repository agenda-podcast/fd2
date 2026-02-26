#!/usr/bin/env python3
import os
import shutil
import sys
import tempfile
import datetime
import subprocess
import re
import json
from pathlib import Path

sys.dont_write_bytecode = True

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.fd_prompt import build_prompt_from_text
from src.gemini_client import call_gemini
from src.role_config import load_role_model_map, model_for_role, endpoint_base, normalize_role_name
from src.fd_manifest import load_manifest_from_text
from src.fd_apply import apply_manifest
from src.fd_zip import zip_dir
from src.fd_release import write_text, write_json, gh_release_create
from src.wi_queue import pick_next_wi_issue_number
from src.github_api import get_issue, create_comment, close_issue, dispatch_workflow
from tools.orchestrator.assemble_app_branch import assemble_stage_for_ms
from tools.check_ascii import run as check_ascii_run
from tools.check_line_limits import run as check_lines_run
from tools.check_no_ellipses import run as check_ellipses_run
from tools.check_no_placeholders import run as check_placeholders_run

MAX_ATTEMPTS = 3

def die(msg: str, code: int = 2) -> int:
    print(msg)
    return code

def _extract_field(text: str, key: str) -> str:
    for line in text.splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return ""

_ROLE_TO_GUIDE = {
    "PM": "ROLE_PM.txt",
    "TECH_LEAD": "ROLE_TECH_LEAD.txt",
    "TECH_WRITER": "ROLE_TECH_WRITER.txt",
    "QA": "ROLE_QA.txt",
    "DEVOPS": "ROLE_DEVOPS.txt",
    "FE": "ROLE_FE.txt",
    "BE": "ROLE_BE.txt",
    "BUILDER": "ROLE_BUILDER.txt",
    "REVIEWER": "ROLE_REVIEWER.txt",
}

def role_guide_for_issue_body(body: str) -> str:
    raw = _extract_field(body, "Owner Role (Producer)") or _extract_field(body, "Receiver Role (Next step)")
    role = normalize_role_name(raw).strip().upper()
    return _ROLE_TO_GUIDE.get(role, "ROLE_BE.txt")

def run_policy_checks(repo_root: str) -> int:
    cwd = os.getcwd()
    for dirpath, dirnames, filenames in os.walk(repo_root):
        if "__pycache__" in dirnames:
            shutil.rmtree(os.path.join(dirpath, "__pycache__"), ignore_errors=True)
        for fn in filenames:
            if fn.endswith(".pyc"):
                try:
                    os.remove(os.path.join(dirpath, fn))
                except Exception:
                    pass
    os.chdir(repo_root)
    try:
        if check_ascii_run(repo_root) != 0:
            return 1
        if check_lines_run(repo_root) != 0:
            return 1
        if check_ellipses_run(repo_root) != 0:
            return 1
        if check_placeholders_run(repo_root) != 0:
            return 1
    finally:
        os.chdir(cwd)
    return 0

def _slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:40] if s else "app"

def _write_app_workflow(stage_root: Path) -> None:
    wf_dir = stage_root / ".github" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    wf = (
        "name: \"App CI\"\n\n"
        "on:\n  push: {}\n\n"
        "jobs:\n  smoke:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: actions/setup-node@v4\n        with:\n          node-version: '20'\n"
        "      - name: Start server and smoke test\n        run: |\n"
        "          node pipeline_app/server.js &\n"
        "          sleep 2\n"
        "          curl -fsS http://127.0.0.1:8080/ > /dev/null\n"
    )
    (wf_dir / "app_ci.yml").write_text(wf, encoding="utf-8")

def _publish_app_branch(repo_root: str, stage: Path, branch_name: str) -> None:
    cwd = os.getcwd()
    os.chdir(repo_root)
    try:
        bot = os.environ.get("FD_BOT_TOKEN", "")
        gh = os.environ.get("GITHUB_TOKEN", "")
        token = bot or gh
        token_src = "FD_BOT_TOKEN" if bot != "" else "GITHUB_TOKEN"
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        if token == "":
            raise RuntimeError("FD_FAIL: missing token for push")
        if repo == "":
            raise RuntimeError("FD_FAIL: missing GITHUB_REPOSITORY for push")

        remote_url = "https://x-access-token:" + token + "@github.com/" + repo + ".git"

        print("FD_DEBUG: app_branch_publish begin")
        print("FD_DEBUG: app_branch_name=" + branch_name)
        print("FD_DEBUG: token_source=" + token_src)
        print("FD_DEBUG: token_present=" + ("1" if token != "" else "0"))
        print("FD_DEBUG: repo=" + repo)

        subprocess.check_call(["git", "config", "user.email", "actions@github.com"])
        subprocess.check_call(["git", "config", "user.name", "github-actions"])
        subprocess.check_call(["git", "remote", "set-url", "origin", remote_url])

        try:
            rv = subprocess.check_output(["git", "remote", "-v"], text=True).strip()
            safe = []
            for line in rv.splitlines():
                if "x-access-token:" in line:
                    safe.append(re.sub(r"x-access-token:[^@]+@", "x-access-token:REDACTED@", line))
                else:
                    safe.append(line)
            print("FD_DEBUG: git_remote_v=" + " | ".join(safe))
        except Exception:
            print("FD_DEBUG: git_remote_v=unavailable")

        # Ensure we have the latest remote state to avoid non-fast-forward failures.
        try:
            subprocess.check_call(["git", "fetch", "origin", branch_name])
            print("FD_DEBUG: git_fetch_branch=ok")
        except Exception:
            print("FD_DEBUG: git_fetch_branch=missing_or_failed")

        subprocess.check_call(["git", "checkout", "-B", branch_name])

        for entry in os.listdir(repo_root):
            if entry == ".git":
                continue
            pp = os.path.join(repo_root, entry)
            if os.path.isdir(pp):
                shutil.rmtree(pp, ignore_errors=True)
            else:
                try:
                    os.remove(pp)
                except Exception:
                    pass

        for entry in os.listdir(stage):
            src = stage / entry
            dst = Path(repo_root) / entry
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)

        subprocess.check_call(["git", "add", "-A"])
        try:
            subprocess.check_call(["git", "commit", "-m", "Publish app snapshot"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

        def _push_force_with_lease() -> None:
            subprocess.check_call(["git", "push", "-u", "origin", branch_name, "--force-with-lease"])

        try:
            _push_force_with_lease()
            print("FD_DEBUG: app_branch_publish push_ok")
            return
        except subprocess.CalledProcessError as exc:
            print("FD_WARN: app_branch_publish push_failed rc=" + str(exc.returncode))
            wf_dir = Path(repo_root) / ".github" / "workflows"
            if wf_dir.exists():
                print("FD_WARN: app_branch_publish removing_workflows_and_retry")
                shutil.rmtree(wf_dir, ignore_errors=True)
                (Path(repo_root) / ".github").mkdir(parents=True, exist_ok=True)
                subprocess.check_call(["git", "add", "-A"])
                try:
                    subprocess.check_call(["git", "commit", "-m", "Remove workflows for app branch"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
                _push_force_with_lease()
                print("FD_DEBUG: app_branch_publish push_ok_without_workflows")
                return
            raise
    finally:
        os.chdir(cwd)

def _policy_enforcement_block(attempt: int, last_error: str) -> str:
    # ASCII-only and no ellipses are hard repository rules.
    # If an attempt fails, we add explicit constraints to force compliance.
    lines = []
    lines.append("")
    lines.append("FD_POLICY_ENFORCEMENT")
    lines.append("This is attempt " + str(attempt) + " of " + str(MAX_ATTEMPTS) + ".")
    if last_error.strip() != "":
        lines.append("Previous attempt failed with: " + last_error.strip())
    lines.append("You MUST output valid JSON ONLY (no code fences, no markdown).")
    lines.append("All file contents MUST be ASCII only (no emoji, no Unicode punctuation).")
    lines.append("Do NOT use three dots anywhere in file contents.")
    lines.append("Do NOT use placeholders like __REPLACE__ME__ or example dot com.")
    lines.append("Do NOT write stubbed or mocked code; implement real logic that runs.")
    lines.append("Keep each non-table logic/code file <= 500 lines.")
    lines.append("manifest.notes MUST be an empty string.")
    lines.append("If you need a bullet list, use '-' and ASCII characters only.")
    lines.append("END_FD_POLICY_ENFORCEMENT")
    lines.append("")
    return "\n".join(lines)

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
    body = str(issue.get("body") or "")

    title = str(issue.get("title") or "")
    wi_id = _extract_field(body, "Work Item ID")
    if wi_id == "":
        m = re.search(r"\bWI-[0-9]{3,}\b", title)
        if m:
            wi_id = m.group(0)
    if wi_id == "":
        wi_id = "WI-" + str(issue_number)


    role_guide = role_guide_override.strip() or role_guide_for_issue_body(body)
    role_map = load_role_model_map()
    raw_role = _extract_field(body, "Owner Role (Producer)") or _extract_field(body, "Receiver Role (Next step)") or "Engineer"
    role = normalize_role_name(raw_role) or "PM"
    model = model_for_role(role, role_map)
    base = endpoint_base(role_map)

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if run_policy_checks(repo_root) != 0:
        return 1

    agent_guides_dir = os.path.join(repo_root, "agent_guides")
    base_prompt = build_prompt_from_text(agent_guides_dir, role_guide, body)

    # Deterministic publish WI: assemble from prior releases, do not call Gemini.
    if wi_id == "WI-AUTO-PUBLISH-APP":
        ms_id = _extract_field(body, "Milestone ID")
        if ms_id == "":
            mms = re.search(r"MS-[0-9]+", title)
            if mms:
                ms_id = mms.group(0)
        if ms_id == "":
            ms_id = "MS-01"
        print("FD_DEBUG: publish_wi assemble ms_id=" + ms_id)
        stage = assemble_stage_for_ms(ms_id, token, Path(repo_root))
        manifest = load_manifest_from_text(json.dumps({
            "schema_version": "FD-ARTIFACT-1.0",
            "work_item_id": wi_id,
            "producer_role": "DevOps",
            "artifact_type": "pipeline_snapshot",
            "files": [{"path": "ASSEMBLED", "content": "1", "content_type": "text/plain", "encoding": "utf-8"}],
            "delete": [],
            "entry_point": None,
            "build_command": None,
            "test_command": None,
            "verification_steps": [],
            "notes": ""
        }))
    else:
        last_err = ""
        last_out = ""
        manifest = None
        stage = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            prompt = base_prompt
            if attempt > 1:
                prompt = prompt + _policy_enforcement_block(attempt, last_err)

            out_text = call_gemini(api_key, prompt, model=model, endpoint_base=base, timeout_s=240)
            last_out = out_text
            if out_text.strip() == "":
                last_err = "FD_FAIL: model returned empty output"
                continue

            try:
                manifest = load_manifest_from_text(out_text)
            except Exception as exc:
                last_err = "FD_FAIL: invalid manifest: " + str(exc)
                continue

            stage = Path(tempfile.mkdtemp(prefix="fd_wi_stage_"))
            pipeline_base = Path(repo_root) / "pipeline_base" / "pipeline_app"
            if pipeline_base.exists():
                shutil.copytree(pipeline_base, stage / "pipeline_app", dirs_exist_ok=True)

            try:
                apply_manifest(manifest, stage)
            except Exception as exc:
                last_err = "FD_FAIL: apply_manifest failed: " + str(exc)
                continue

            break

        if manifest is None or stage is None:
            return die("FD_FAIL: wi execution failed after " + str(MAX_ATTEMPTS) + " attempts: " + last_err, 1)

        # Enforce special WI behaviors deterministically.
    if wi_id == "WI-AUTO-PUBLISH-APP":
        if manifest.artifact_type != "pipeline_snapshot":
            print("FD_WARN: overriding manifest.artifact_type to pipeline_snapshot for WI-AUTO-PUBLISH-APP")
            manifest.artifact_type = "pipeline_snapshot"

# If this WI produces an app snapshot, ensure the app branch has its own CI workflow.
    if manifest.artifact_type == "pipeline_snapshot":
        if os.environ.get("FD_BOT_TOKEN", "") != "":
            _write_app_workflow(stage)
        else:
            print("FD_WARN: skipping app workflow creation because FD_BOT_TOKEN is not set")
            wfdir = stage / ".github" / "workflows"
            if wfdir.exists():
                try:
                    shutil.rmtree(wfdir, ignore_errors=True)
                except Exception:
                    pass

    artifacts_dir = Path(tempfile.mkdtemp(prefix="fd_wi_artifacts_"))
    artifact_zip = artifacts_dir / "artifact.zip"
    zip_dir(stage, artifact_zip)

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    # wi_id is computed earlier from issue body/title
    rel_tag = "FD-" + wi_id + "-" + now

    manifest_path = artifacts_dir / "manifest.json"
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
        "delete": manifest.delete,
    })
    log_path = artifacts_dir / "runner_log.txt"
    write_text(log_path, "WI issue_number=" + str(issue_number) + "\nrole_guide=" + role_guide + "\nmodel=" + model + "\n")
    report_path = artifacts_dir / "verification_report.txt"
    write_text(report_path, "FD_WI_EXECUTED\nWI=" + wi_id + "\nISSUE=" + str(issue_number) + "\n")

    gh_release_create(rel_tag, "WI " + wi_id, "FD WI artifact for " + wi_id, [str(artifact_zip), str(manifest_path), str(log_path), str(report_path)])

    create_comment(issue_number, "FD_WI_DONE\nRELEASE=" + rel_tag, token)
    close_issue(issue_number, token)

    # Publish app branch if requested.
    if manifest.artifact_type == "pipeline_snapshot":
        ms_id = _extract_field(body, "Milestone ID")
        if ms_id == "":
            m = re.search(r"MS-[0-9]+", title)
            if m:
                ms_id = m.group(0)
        if ms_id == "":
            ms_id = "MS-01"
        branch_name = "app-" + _slug(ms_id)
        try:
            _publish_app_branch(repo_root, stage, branch_name)
            create_comment(issue_number, "FD_APP_BRANCH_PUBLISHED\nBRANCH=" + branch_name, token)
        except Exception as exc:
            print("FD_WARN: app branch publish failed: " + str(exc))

    # Dispatch next WI once. Exclude current issue number to avoid eventual consistency loops.
    if os.environ.get("FD_BOT_TOKEN", "") != "":
        next_issue = pick_next_wi_issue_number(token, exclude={issue_number})
        if next_issue != 0 and next_issue != issue_number:
            try:
                dispatch_workflow("orchestrate_wi_issue.yml", "main", {"issue_number": str(next_issue), "role_guide": ""}, token)
            except RuntimeError as exc:
                print("FD_WARN: dispatch_workflow failed: " + str(exc))

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
