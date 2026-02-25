#!/usr/bin/env python3
import os
import sys
import tempfile
import datetime
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.fd_prompt import build_prompt
from src.gemini_client import call_gemini
from src.fd_manifest import load_manifest_from_text
from src.fd_apply import apply_manifest
from src.fd_zip import zip_dir
from src.fd_release import write_text, write_json, gh_release_create
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

def main() -> int:
    if len(sys.argv) != 4:
        sys.stdout.write("usage: run_wi.py <WI_PATH> <ROLE_GUIDE_FILE> <ARTIFACT_TYPE>\n")
        return 2

    wi_path = sys.argv[1]
    role_guide_file = sys.argv[2]
    artifact_type = sys.argv[3]

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if api_key == "":
        die("FD_FAIL: missing GEMINI_API_KEY")

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    prompt = build_prompt(os.path.join(repo_root, "agent_guides"), role_guide_file, wi_path)

    out_text = call_gemini(api_key, prompt, timeout_s=180)
    manifest = load_manifest_from_text(out_text)

    if manifest.artifact_type != artifact_type:
        die("FD_FAIL: artifact_type mismatch expected=" + artifact_type)

    ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    tag = "FD-" + manifest.work_item_id + "-" + manifest.producer_role.replace(" ", "_") + "-" + ts

    with tempfile.TemporaryDirectory() as tmp:
        stage = os.path.join(tmp, "stage")
        os.makedirs(stage, exist_ok=True)

        # Build output tree in stage:
        # - If pipeline_snapshot: start from pipeline_base then apply manifest
        # - If repo_patch: start from current repo and apply manifest (produces patch snapshot)
        if artifact_type == "pipeline_snapshot":
            _copy_tree(os.path.join(repo_root, "pipeline_base"), stage)
        else:
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

        notes = "FD WI artifact for " + manifest.work_item_id
        gh_release_create(tag, tag, notes, [manifest_path, zip_path, verification_path])

        # Update pipeline branch when pipeline snapshot
        if artifact_type == "pipeline_snapshot":
            _sync_pipeline_branch(repo_root, zip_path, tag)

    sys.stdout.write("FD_OK: release_tag=" + tag + "\n")
    return 0

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

def _sync_pipeline_branch(repo_root: str, artifact_zip: str, release_tag: str) -> None:
    import subprocess
    import zipfile
    tmp = tempfile.mkdtemp()
    with zipfile.ZipFile(artifact_zip, "r") as z:
        z.extractall(tmp)

    def run(cmd):
        subprocess.check_call(cmd, cwd=repo_root)

    run(["git", "fetch", "origin"])
    run(["git", "checkout", "-B", "pipeline"])
    # Remove tracked files (except .git)
    for item in os.listdir(repo_root):
        if item == ".git":
            continue
        p = os.path.join(repo_root, item)
        if os.path.isdir(p):
            subprocess.check_call(["git", "rm", "-r", "-f", item], cwd=repo_root)
        else:
            subprocess.check_call(["git", "rm", "-f", item], cwd=repo_root)

    # Copy extracted artifact into repo root
    for dirpath, dirnames, filenames in os.walk(tmp):
        rel = os.path.relpath(dirpath, tmp)
        out_dir = os.path.join(repo_root, rel) if rel != "." else repo_root
        os.makedirs(out_dir, exist_ok=True)
        for fn in filenames:
            s = os.path.join(dirpath, fn)
            d = os.path.join(out_dir, fn)
            with open(s, "rb") as rf:
                data = rf.read()
            with open(d, "wb") as wf:
                wf.write(data)

    run(["git", "add", "-A"])
    run(["git", "commit", "-m", "Sync pipeline from " + release_tag])
    run(["git", "push", "-f", "origin", "pipeline"])

if __name__ == "__main__":
    raise SystemExit(main())
