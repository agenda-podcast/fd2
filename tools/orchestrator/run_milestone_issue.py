#!/usr/bin/env python3
import datetime
import os
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.fd_prompt import build_prompt_from_text
from src.gemini_client import call_gemini
from src.role_config import load_role_model_map, role_from_guide_filename, model_for_role, endpoint_base
from src.role_config import normalize_role_name
from src.fd_manifest import load_manifest_from_text
from src.fd_apply import apply_manifest
from src.fd_zip import zip_dir
from src.fd_release import write_json, write_text, gh_release_create
from src.github_api import get_issue, create_issue, create_comment, close_issue, dispatch_workflow

from tools.check_line_limits import run as check_lines_run
from tools.check_no_ellipses import run as check_ellipses_run
import re
from typing import List


def die(msg: str) -> None:
    sys.stdout.write(msg + "\n")
    raise SystemExit(1)


def run_policy_checks(repo_root: str) -> None:
    cwd = os.getcwd()
    # Remove runtime bytecode artifacts to keep policy checks deterministic
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
            die("FD_FAIL: policy ascii")
        if check_lines_run(repo_root) != 0:
            die("FD_FAIL: policy line limits")
        if check_ellipses_run(repo_root) != 0:
            die("FD_FAIL: policy ellipses")
    finally:
        os.chdir(cwd)


def _extract_ms_id_from_title(title: str) -> str:
    # Accept formats like "MS-01" followed by text, or "MS-001" followed by text.
    t = title.strip()
    if not t.startswith("MS-"):
        return ""
    parts = t.split()
    return parts[0]

def _extract_field(text: str, key: str) -> str:
    for line in (text or "").splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return ""


def _extract_ms_id_from_body(body: str) -> str:
    # Preferred: a Milestone template line.
    # Example: "Milestone ID: MS-000".
    for line in (body or "").splitlines():
        s = line.strip()
        if not s.lower().startswith("milestone id:"):
            continue
        val = s.split(":", 1)[1].strip()
        if val.startswith("MS-"):
            return val.split()[0]
    return ""


def _extract_ms_id(title: str, body: str) -> str:
    ms = _extract_ms_id_from_title(title)
    if ms != "":
        return ms
    return _extract_ms_id_from_body(body)


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
    ms_id = _extract_ms_id(title, body)
    if ms_id == "":
        die("FD_FAIL: cannot determine milestone id. Use title prefix 'MS-' or include 'Milestone ID: MS-###' in issue body")

    issue_text = "TITLE\n" + title + "\n\nBODY\n" + body + "\n"
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    prompt = build_prompt_from_text(os.path.join(repo_root, "agent_guides"), role_guide_file, issue_text)
    # Milestone planning is a special run: we require a deterministic manifest that
    # tags the output as the milestone id and produces a repo_patch handoff.
    # The model sometimes outputs WI-style ids or a different artifact_type.
    # We both (1) instruct explicitly and (2) enforce deterministically after parsing.
    prompt = (
        prompt
        + "\n\nFD_MILESTONE_CONSTRAINTS\n"
        + "- work_item_id MUST equal the milestone id: "
        + ms_id
        + "\n"
        + "- artifact_type MUST equal repo_patch\n"
    )

    role_map = load_role_model_map()
    role = role_from_guide_filename(role_guide_file)
    model = model_for_role(role, role_map)
    ep_base = endpoint_base(role_map)
    out_text = call_gemini(api_key, prompt, timeout_s=240, model=model, endpoint_base=ep_base)
    if (out_text or "").strip() == "":
        die("FD_FAIL: model returned empty output role=" + role + " model=" + model)
    manifest = load_manifest_from_text(out_text)

    if manifest.work_item_id != ms_id:
        sys.stdout.write(
            "FD_WARN: overriding manifest.work_item_id to milestone id expected="
            + ms_id
            + " got="
            + str(manifest.work_item_id)
            + "\n"
        )
        manifest.work_item_id = ms_id

    if manifest.artifact_type != "repo_patch":
        sys.stdout.write(
            "FD_WARN: overriding manifest.artifact_type to repo_patch expected=repo_patch got="
            + str(manifest.artifact_type)
            + "\n"
        )
        manifest.artifact_type = "repo_patch"

    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    tag = "FD-" + ms_id + "-PM-" + ts

    created_wi_links = []
    wi_created = 0

    with tempfile.TemporaryDirectory() as tmp:
        stage = os.path.join(tmp, "stage")
        os.makedirs(stage, exist_ok=True)

        # Stage starts empty. For milestone planning, we only package the produced handoff files.
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

        # Create WI issues from manifest file entries (breadth-first by Task Number).
        wi_items = []
        for f in manifest.files:
            if not f.path.startswith("handoff/work_items/"):
                continue
            if not f.path.endswith(".md"):
                continue
            tn = ""
            wi_id = ""
            for line in f.content.splitlines():
                if line.startswith("Task Number:"):
                    tn = line.split(":", 1)[1].strip()
                elif line.startswith("Work Item ID:"):
                    wi_id = line.split(":", 1)[1].strip()
            def _task_key(task_num: str):
                s = task_num.strip()
                if s == "":
                    return (9999,)
                if not re.match(r"^[0-9]+(\.[0-9]+)*$", s):
                    return (9999,)
                parts = [int(x) for x in s.split(".") if x.strip() != ""]
                pad = 8
                padded = parts[:pad] + [9999] * max(0, pad - len(parts))
                return tuple(padded)
            wi_items.append((_task_key(tn), wi_id, f.content))


                # FD_VALIDATE_WI_HEADERS
        _validate_wi_headers(ms_id, [x[2] for x in wi_items])

        wi_items.sort(key=lambda x: (x[0], x[1]))

        for item in wi_items:
            wi_body = item[2]
            wi_title = _wi_title_from_body(wi_body)
            if wi_title == "":
                wi_title = "Work Item"
            created = create_issue(wi_title, wi_body, gh_token)
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

    # Close milestone planning issue (planning completed)
    close_issue(issue_number, gh_token)

    # Dispatch first WI automatically in breadth-first order
    bot_token = os.environ.get("FD_BOT_TOKEN", "")
    if bot_token != "":
        first_wi = 0
        if len(created_wi_links) > 0:
            # created_wi_links entries: "#<num> <url>"
            try:
                first_wi = int(created_wi_links[0].split()[0].lstrip("#"))
            except Exception:
                first_wi = 0
        if first_wi != 0:
            dispatch_workflow("orchestrate_wi_issue.yml", "main", {"issue_number": str(first_wi), "role_guide": ""}, bot_token)

    sys.stdout.write("FD_OK: release_tag=" + tag + " wi_created=" + str(wi_created) + "\n")
    return 0



def _validate_wi_headers(ms_id: str, wi_bodies: List[str]) -> None:
    # Enforce small effective team and correct producer roles.
    # Exactly 4 work items required for each milestone.
    if len(wi_bodies) != 4:
        raise RuntimeError("FD_FAIL: milestone must produce exactly 4 work items got=" + str(len(wi_bodies)))

    want = [
        ("BUILDER", "REVIEWER"),
        ("REVIEWER", "TECH_WRITER"),
        ("TECH_WRITER", "DEVOPS"),
        ("DEVOPS", "OWNER"),
    ]

    def _fail(msg: str, body: str) -> None:
        head = "\n".join((body or "").splitlines()[:24])
        raise RuntimeError(msg + "\nFD_CONTEXT_HEAD:\n" + head)

    idx = 0
    for body in wi_bodies:
        wi_id = _extract_field(body, "Work Item ID")
        if wi_id == "":
            _fail("FD_FAIL: WI missing Work Item ID idx=" + str(idx), body)

        ms = _extract_field(body, "Milestone ID")
        if ms == "":
            _fail("FD_FAIL: WI missing Milestone ID wi=" + wi_id, body)
        if ms.strip() != ms_id.strip():
            _fail("FD_FAIL: WI Milestone ID mismatch wi=" + wi_id + " got=" + ms + " expected=" + ms_id, body)

        prod = normalize_role_name(_extract_field(body, "Owner Role (Producer)")).upper()
        recv_raw = _extract_field(body, "Receiver Role (Next step)")
        recv = normalize_role_name(recv_raw).upper()
        title = _extract_field(body, "Title")

        exp_prod, exp_recv = want[idx]
        if prod != exp_prod:
            _fail("FD_FAIL: invalid Producer role wi=" + wi_id + " got=" + prod + " expected=" + exp_prod + " title=" + title, body)

        if exp_recv == "OWNER":
            if recv_raw.strip().upper() != "OWNER":
                _fail("FD_FAIL: invalid Receiver role wi=" + wi_id + " got=" + recv_raw + " expected=Owner", body)
        else:
            if recv != exp_recv:
                _fail("FD_FAIL: invalid Receiver role wi=" + wi_id + " got=" + recv + " expected=" + exp_recv + " title=" + title, body)

        idx += 1

def _wi_title_from_body(body: str) -> str:
    wi_id = ""
    task_num = ""
    title = ""
    recv = ""
    for line in body.splitlines():
        if line.startswith("Work Item ID:"):
            wi_id = line.split(":", 1)[1].strip()
        elif line.startswith("Task Number:"):
            task_num = line.split(":", 1)[1].strip()
        elif line.startswith("Title:"):
            title = line.split(":", 1)[1].strip()
        elif line.startswith("Receiver Role (Next step):"):
            recv = line.split(":", 1)[1].strip()
    parts = []
    if wi_id != "":
        parts.append(wi_id)
    if task_num != "":
        parts.append(task_num)
    if title != "":
        parts.append("-")
        parts.append(title)
    if recv != "":
        parts.append("->")
        parts.append(recv)
    if len(parts) == 0:
        return ""
    return "Work Item: " + " ".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
