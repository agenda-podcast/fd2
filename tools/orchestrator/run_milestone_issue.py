#!/usr/bin/env python3
import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.fd_prompt import build_prompt_from_text
from src.gemini_client import call_gemini
from src.fd_manifest import load_manifest_from_text
from src.fd_apply import apply_manifest
from src.fd_zip import zip_dir
from src.fd_release import write_json, write_text, gh_release_create
from src.github_api import get_issue, create_issue, create_comment

from tools.check_ascii import main as check_ascii_main
from tools.check_line_limits import main as check_lines_main
from tools.check_no_ellipses import main as check_ellipses_main


def die(msg: str) -> None:
    sys.stdout.write(msg + "\n")
    raise SystemExit(1)


def run_policy_checks(repo_root: str) -> None:
    cwd = os.getcwd()
    os.chdir(repo_root)
    try:
        if check_ascii_main(repo_root) != 0:
            die("FD_FAIL: policy ascii")
        if check_lines_main(repo_root) != 0:
            die("FD_FAIL: policy line limits")
        if check_ellipses_main(repo_root) != 0:
            die("FD_FAIL: policy ellipses")
    finally:
        os.chdir(cwd)


def _extract_ms_id(title: str) -> str:
    # Accept formats like "MS-01" followed by text, or "MS-001" followed by text.
    t = title.strip()
    if not t.startswith("MS-"):
        return ""
    parts = t.split()
    return parts[0]


def main() -> int:
    if len(sys.argv) != 3:
        sys.stdout.write("usage: run_milestone_issue.py <ISSUE_NUMBER> <ROLE_GUIDE_FILE>\n")
        return 2

    issue_number = int(sys.argv[1])
    role_guide_file = sys.argv[2]

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if api_key == "":
        die("FD_FAIL: missing GEMINI_API_KEY")

    gh_token = os.environ.get("GITHUB_TOKEN", "")
    if gh_token == "":
        die("FD_FAIL: missing GITHUB_TOKEN")

    issue = get_issue(issue_number, gh_token)
    title = str(issue.get("title", "")).strip()
    body = str(issue.get("body", "")).strip()
    ms_id = _extract_ms_id(title)
    if ms_id == "":
        die("FD_FAIL: issue title must start with MS-")

    issue_text = "TITLE\n" + title + "\n\nBODY\n" + body + "\n"
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    prompt = build_prompt_from_text(os.path.join(repo_root, "agent_guides"), role_guide_file, issue_text)

    out_text = call_gemini(api_key, prompt, timeout_s=240)
    manifest = load_manifest_from_text(out_text)

    if manifest.work_item_id != ms_id:
        die("FD_FAIL: work_item_id must equal milestone id expected=" + ms_id)
    if manifest.artifact_type != "repo_patch":
        die("FD_FAIL: artifact_type must be repo_patch")

    ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    tag = "FD-" + ms_id + "-PM-" + ts

    created_wi_links = []
    wi_created = 0

    with tempfile.TemporaryDirectory() as tmp:
        stage = os.path.join(tmp, "stage")
        os.makedirs(stage, exist_ok=True)

        # Stage is repo snapshot + injected handoff files, used only for artifact.zip.
        _copy_tree(repo_root, stage)
        apply_manifest(manifest, stage)
        run_policy_checks(stage)

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
                {
                    "path": f.path,
                    "content_type": f.content_type,
                    "encoding": f.encoding
                } for f in manifest.files
            ],
            "delete": manifest.delete
        })

        verification_path = os.path.join(tmp, "verification_report.txt")
        write_text(verification_path, "\n".join(manifest.verification_steps) + "\n")

        zip_path = os.path.join(tmp, "artifact.zip")
        zip_dir(stage, zip_path, exclude_prefixes=[".git/"])

        notes = "FD milestone planning artifact for " + ms_id
        gh_release_create(tag, tag, notes, [manifest_path, zip_path, verification_path])

        # Create WI issues from manifest file entries.
        for f in manifest.files:
            if not f.path.startswith("handoff/work_items/"):
                continue
            if not f.path.endswith(".md"):
                continue
            wi_title = _wi_title_from_body(f.content)
            if wi_title == "":
                wi_title = os.path.basename(f.path)
            created = create_issue(wi_title, f.content, gh_token)
            wi_created += 1
            created_wi_links.append("#" + str(created.get("number")) + " " + str(created.get("html_url")))

    comment_lines = []
    comment_lines.append("FD_MILESTONE_PLANNED")
    comment_lines.append("MS=" + ms_id)
    comment_lines.append("RELEASE=" + tag)
    comment_lines.append("WI_CREATED=" + str(wi_created))
    for l in created_wi_links:
        comment_lines.append("WI=" + l)
    create_comment(issue_number, "\n".join(comment_lines) + "\n", gh_token)

    sys.stdout.write("FD_OK: release_tag=" + tag + " wi_created=" + str(wi_created) + "\n")
    return 0


def _wi_title_from_body(body: str) -> str:
    for line in body.splitlines():
        s = line.strip()
        if s.lower().startswith("title:"):
            return s.split(":", 1)[1].strip()
        if s.lower().startswith("work item id:"):
            # Keep reading for a Title line
            continue
        if s.lower().startswith("work item id"):
            continue
    # Fallback: use first heading
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("#"):
            return s.lstrip("#").strip()
    return ""


def _copy_tree(src: str, dst: str) -> None:
    for dirpath, dirnames, filenames in os.walk(src):
        rel = os.path.relpath(dirpath, src)
        out_dir = os.path.join(dst, rel) if rel != "." else dst
        os.makedirs(out_dir, exist_ok=True)
        for fn in filenames:
            s = os.path.join(dirpath, fn)
            d = os.path.join(out_dir, fn)
            with open(s, "rb") as rf:
                data = rf.read()
            with open(d, "wb") as wf:
                wf.write(data)


if __name__ == "__main__":
    raise SystemExit(main())
