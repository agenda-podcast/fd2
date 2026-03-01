#!/usr/bin/env python3
import glob
import io
import os
import subprocess
import sys
import tempfile
import time
import traceback
import re
import hashlib
import shutil
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional

FD_PROMPT_MAX_LOG_CHARS = int(os.environ.get('FD_PROMPT_MAX_LOG_CHARS','40000') or '40000')
FD_PROMPT_MAX_CTX_CHARS = int(os.environ.get('FD_PROMPT_MAX_CTX_CHARS','60000') or '60000')
FD_PROMPT_MAX_RELATED_FILES = int(os.environ.get('FD_PROMPT_MAX_RELATED_FILES','12') or '12')
FD_PROMPT_MAX_FILE_CHARS = int(os.environ.get('FD_PROMPT_MAX_FILE_CHARS','12000') or '12000')
FD_PROMPT_MAX_RELATED_TOTAL_CHARS = int(os.environ.get('FD_PROMPT_MAX_RELATED_TOTAL_CHARS','80000') or '80000')

sys.path.insert(0, os.path.abspath(os.getcwd()))

from src.fd_auto.actions_api import (
    dispatch_workflow,
    download_artifact_zip,
    download_run_logs_zip,
    extract_logs_text,
    find_latest_run_id,
    list_run_artifacts,
    wait_run_complete,
)
from src.fd_auto.gemini_client import call_gemini

def _preview(s: str, n: int = 600) -> str:
    t = (s or "").replace("\r\n","\n").replace("\r","\n")
    t = t.replace("\n", " ")
    if len(t) > n:
        return t[:n] + " [TRUNC]"
    return t

def _step(msg: str) -> None:
    print("FD_STEP: " + msg)

def _write(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8", errors="ignore")

def _read_text_if_exists(p: Path, max_chars: int = 120000) -> str:
    if not p.exists():
        return ""
    txt = p.read_text(encoding="utf-8", errors="ignore")
    if len(txt) > max_chars:
        return txt[:max_chars] + "\n"
    return txt


def _sha256_text(s: str) -> str:
    h = hashlib.sha256()
    h.update((s or "").encode("utf-8", errors="ignore"))
    return h.hexdigest()


def _diff_touched_files(diff_text: str) -> List[str]:
    files: List[str] = []
    for line in (diff_text or "").splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"^diff --git a/(.+) b/(.+)\\s*$", line.strip())
            if m:
                f = m.group(2).strip()
                if f not in files:
                    files.append(f)
    return files


def _diff_new_files(diff_text: str) -> Set[str]:
    new_files: Set[str] = set()
    cur_file = ""
    saw_new_mode = False
    for line in (diff_text or "").splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"^diff --git a/(.+) b/(.+)\\s*$", line.strip())
            cur_file = m.group(2).strip() if m else ""
            saw_new_mode = False
            continue
        if line.startswith("new file mode"):
            saw_new_mode = True
            continue
        if cur_file and saw_new_mode:
            new_files.add(cur_file)
            saw_new_mode = False
    return new_files


def _diff_mentions_requirements_install(diff_text: str) -> bool:
    for line in (diff_text or "").splitlines():
        if not line.startswith("+"):
            continue
        t = line[1:]
        if "pip install -r requirements.txt" in t or "pip3 install -r requirements.txt" in t:
            return True
    return False


def _validate_requirements_install(repo_dir: Path, diff_text: str) -> Tuple[bool, str]:
    # Accept creation of new files via unified diff.
    # If a diff adds a pip install -r requirements.txt line, accept it only if requirements.txt exists
    # or the diff creates requirements.txt as a new file.
    if not _diff_mentions_requirements_install(diff_text):
        return True, ""
    req_path = repo_dir / "requirements.txt"
    new_files = _diff_new_files(diff_text)
    if req_path.exists():
        return True, ""
    if "requirements.txt" in new_files:
        return True, ""
    return False, "stability_violation: diff adds 'pip install -r requirements.txt' but requirements.txt does not exist and is not created in the diff"


def _collect_paths_from_evidence(text: str, max_items: int = 50) -> List[str]:
    if not text:
        return []
    pats = [
        r"(\\.github/workflows/[A-Za-z0-9_./\\-]+\\.ya?ml)",
        r"(src/[A-Za-z0-9_./\\-]+\\.py)",
        r"(tools/[A-Za-z0-9_./\\-]+\\.py)",
        r"(fd_policy/[A-Za-z0-9_./\\-]+\\.txt)",
        r"(docs/[A-Za-z0-9_./\\-]+)",
    ]
    out: List[str] = []
    for pat in pats:
        for m in re.finditer(pat, text):
            pth = m.group(1)
            if pth and pth not in out:
                out.append(pth)
            if len(out) >= max_items:
                return out
    return out


def _compute_allowed_files(workflow_file: str, evidence_text: str, extra_paths: Optional[List[str]] = None) -> List[str]:
    allowed: List[str] = []
    wf = ".github/workflows/" + workflow_file.strip()
    if workflow_file.strip() != "" and wf not in allowed:
        allowed.append(wf)
    for pth in _collect_paths_from_evidence(evidence_text):
        if pth not in allowed:
            allowed.append(pth)
    if extra_paths:
        for pth in extra_paths:
            pth2 = (pth or "").strip()
            if pth2 != "" and pth2 not in allowed:
                allowed.append(pth2)
    return allowed[:80]


def _expand_related_files(wt_dir: Path, base_paths: List[str]) -> List[str]:
    # Expand evidence file paths to include directly-related local files.
    # Strategy:
    # - include the file itself if exists
    # - include __init__.py in the same directory (if exists)
    # - include up to 5 sibling .py files in same directory (stable sorted)
    out: List[str] = []
    seen: Set[str] = set()
    for rel in base_paths:
        rel = (rel or "").strip().lstrip("./")
        if rel == "":
            continue
        if rel in seen:
            continue
        seen.add(rel)
        out.append(rel)

        abs_path = wt_dir / rel
        parent = abs_path.parent
        if parent.exists() and parent.is_dir():
            init_rel = str((parent / "__init__.py").relative_to(wt_dir)) if (parent / "__init__.py").exists() else ""
            if init_rel and init_rel not in seen:
                seen.add(init_rel)
                out.append(init_rel)

            sibs: List[str] = []
            try:
                for p in sorted(parent.iterdir(), key=lambda x: x.name):
                    if not p.is_file():
                        continue
                    if p.suffix != ".py":
                        continue
                    sib_rel = str(p.relative_to(wt_dir))
                    if sib_rel in seen:
                        continue
                    sibs.append(sib_rel)
            except Exception:
                sibs = []
            for sib_rel in sibs[:5]:
                seen.add(sib_rel)
                out.append(sib_rel)
    return out


def _read_text_file_limited(path: Path, max_chars: int) -> str:
    try:
        s = path.read_text(errors="replace")
    except Exception:
        return ""
    if max_chars > 0 and len(s) > max_chars:
        return s[:max_chars] + "\n[TRUNC]\n"
    return s


def _read_related_files_context(wt_dir: Path, related: List[str]) -> str:
    total = 0
    blocks: List[str] = []
    for rel in related:
        if len(blocks) >= FD_PROMPT_MAX_RELATED_FILES:
            break
        rel = (rel or "").strip().lstrip("./")
        if rel == "":
            continue
        abs_path = wt_dir / rel
        if not abs_path.exists() or not abs_path.is_file():
            continue
        # skip very large/binary-ish files
        try:
            size = abs_path.stat().st_size
        except Exception:
            size = 0
        if size > 500000:
            continue
        txt = _read_text_file_limited(abs_path, FD_PROMPT_MAX_FILE_CHARS)
        if txt.strip() == "":
            continue
        block = "FILE: " + rel + "\n" + txt + "\n"
        if total + len(block) > FD_PROMPT_MAX_RELATED_TOTAL_CHARS:
            break
        blocks.append(block)
        total += len(block)
    return "\n".join(blocks).strip() + ("\n" if blocks else "")


def _read_repo_guide(wt_dir: Path) -> str:
    p = wt_dir / "fd_context" / "repo_guide.txt"
    return _read_text_if_exists(p)
def _validate_unified_diff_only(resp_text: str) -> Tuple[bool, str]:
    tx = (resp_text or "").replace("\\r\\n", "\\n").replace("\\r", "\\n")
    if not tx.startswith("diff --git "):
        return False, "format_violation: response must start with 'diff --git'"
    if "--- a/" not in tx or "+++ b/" not in tx:
        return False, "format_violation: missing ---/+++ headers"
    if "@@" not in tx and "new file mode" not in tx and "deleted file mode" not in tx:
        return False, "format_violation: missing hunks (no @@) or file mode markers"
    return True, ""


def _validate_scope(diff_text: str, allowed_files: List[str]) -> Tuple[bool, str]:
    touched = _diff_touched_files(diff_text)
    new_files = _diff_new_files(diff_text)
    allowed_set = set(allowed_files or [])
    # Allow new files (created via unified diff) even if not in ALLOWED_FILES.
    bad = [f for f in touched if (f not in allowed_set and f not in new_files)]
    if bad:
        return False, "scope_violation: diff touches files not in ALLOWED_FILES: " + ",".join(bad[:15])
    return True, ""


def _detect_secret_var_flips(diff_text: str) -> List[Tuple[str, str, str]]:
    flips: List[Tuple[str, str, str]] = []
    cur_file = ""
    last_removed = ""
    for line in (diff_text or "").splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"^diff --git a/(.+) b/(.+)\\s*$", line.strip())
            if m:
                cur_file = m.group(2).strip()
            last_removed = ""
            continue
        if line.startswith("-"):
            last_removed = line
            continue
        if line.startswith("+") and last_removed:
            rm = last_removed
            add = line
            m1 = re.search(r"\\$\\{\\{\\s*secrets\\.([A-Za-z0-9_]+)\\s*\\}\\}", rm)
            m2 = re.search(r"\\$\\{\\{\\s*vars\\.([A-Za-z0-9_]+)\\s*\\}\\}", add)
            if m1 and m2 and m1.group(1) == m2.group(1):
                flips.append(("secrets_to_vars", m1.group(1), cur_file))
            m3 = re.search(r"\\$\\{\\{\\s*vars\\.([A-Za-z0-9_]+)\\s*\\}\\}", rm)
            m4 = re.search(r"\\$\\{\\{\\s*secrets\\.([A-Za-z0-9_]+)\\s*\\}\\}", add)
            if m3 and m4 and m3.group(1) == m4.group(1):
                flips.append(("vars_to_secrets", m3.group(1), cur_file))
            last_removed = ""
    return flips


def _run(cmd: List[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

def _parse_inputs(s: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in (s or "").splitlines():
        t = line.strip()
        if t == "" or t.startswith("#"):
            continue
        if "=" not in t:
            continue
        k, v = t.split("=", 1)
        out[k.strip()] = v.strip()
    return out

def _cleanup_pycache(repo_dir: Path, artifacts: Path, label: str) -> None:
    removed_files = 0
    removed_dirs = 0
    for root, dirs, files in os.walk(str(repo_dir)):
        dn = [d for d in list(dirs) if d == "__pycache__"]
        for d in dn:
            p = Path(root) / d
            try:
                shutil.rmtree(str(p))
                removed_dirs += 1
            except Exception:
                pass
            try:
                dirs.remove(d)
            except Exception:
                pass
        for f in files:
            if not f.endswith(".pyc"):
                continue
            p2 = Path(root) / f
            try:
                p2.unlink()
                removed_files += 1
            except Exception:
                pass
    _write(artifacts / (label + "_pycache_cleanup.log"), "removed_dirs=" + str(removed_dirs) + " removed_files=" + str(removed_files) + "\n")

def _prepare_git_auth(repo_dir: Path, token: str, artifacts: Path, label: str) -> None:
    # Log current auth-related settings and force PAT-based auth (avoid actions/checkout extraheader taking precedence).
    try:
        rem = _run(["git", "remote", "-v"], str(repo_dir)).stdout
        _write(artifacts / (label + "_remote_v.log"), rem)
    except Exception:
        pass
    try:
        eh = _run(["git", "config", "--local", "--get-all", "http.https://github.com/.extraheader"], str(repo_dir)).stdout
        _write(artifacts / (label + "_extraheader_before.log"), eh)
    except Exception:
        pass
    # Remove checkout-injected auth header so remote URL token is used.
    _run(["git", "config", "--local", "--unset-all", "http.https://github.com/.extraheader"], str(repo_dir))
    try:
        eh2 = _run(["git", "config", "--local", "--get-all", "http.https://github.com/.extraheader"], str(repo_dir)).stdout
        _write(artifacts / (label + "_extraheader_after.log"), eh2)
    except Exception:
        pass
    # Set origin URL with PAT token.
    repo = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
    if repo == "":
        raise RuntimeError("FD_FAIL: missing GITHUB_REPOSITORY")
    remote_url = "https://x-access-token:" + token + "@github.com/" + repo + ".git"
    subprocess.check_call(["git", "remote", "set-url", "origin", remote_url], cwd=str(repo_dir))
    _step("git_auth_prepared label=" + label)

def _push_with_fallback(wt_dir: Path, repo_root: Path, artifacts: Path, label: str, primary_token: str, fallback_token: str) -> subprocess.CompletedProcess:
    # Attempt push with primary token. If blocked by workflow-permission restriction for GitHub App, retry with fallback token.
    _prepare_git_auth(Path(wt_dir), primary_token, artifacts, label + "_prep_primary")
    _prepare_git_auth(repo_root, primary_token, artifacts, label + "_prep_primary_root")
    p1 = _run(["git", "push", "--force-with-lease"], str(wt_dir))
    _write(artifacts / (label + "_push_primary.log"), p1.stdout)
    if p1.returncode == 0:
        return p1
    msg = (p1.stdout or "")
    if "refusing to allow a GitHub App to create or update workflow" in msg and fallback_token.strip() != "":
        _step("push_retry_with_fallback_token")
        _prepare_git_auth(Path(wt_dir), fallback_token, artifacts, label + "_prep_fallback")
        _prepare_git_auth(repo_root, fallback_token, artifacts, label + "_prep_fallback_root")
        p2 = _run(["git", "push", "--force-with-lease"], str(wt_dir))
        _write(artifacts / (label + "_push_fallback.log"), p2.stdout)
        return p2
    return p1

def _set_origin_with_token(repo_root: Path, token: str) -> None:
    repo = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
    if repo == "":
        raise RuntimeError("FD_FAIL: missing GITHUB_REPOSITORY")
    remote_url = "https://x-access-token:" + token + "@github.com/" + repo + ".git"
    subprocess.check_call(["git","remote","set-url","origin",remote_url], cwd=str(repo_root))

def _ensure_worktree(branch: str) -> tuple[Path, Path]:
    repo_root = Path(os.getcwd())
    wt_dir = Path(tempfile.mkdtemp(prefix="fd_tune_wt_"))
    subprocess.check_call(["git","fetch","origin",branch], cwd=str(repo_root))
    subprocess.check_call(["git","worktree","add",str(wt_dir),branch], cwd=str(repo_root))
    return wt_dir, repo_root

def _read_latest_snapshot(wt_dir: Path) -> str:
    snap_dir = wt_dir / "docs" / "assets" / "app"
    if not snap_dir.exists():
        return ""
    snaps = sorted([str(p) for p in snap_dir.glob("app-source_*.txt")])
    if not snaps:
        return ""
    return Path(snaps[-1]).read_text(encoding="utf-8", errors="ignore")

def _upload_snapshot_chunks(snapshot_text: str, out_dir: Path) -> None:
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
        prompt = ""
        prompt += "TASK: Receive repository snapshot chunk. Reply only with: ACK " + str(i+1) + "/" + str(total) + "\n"
        prompt += "SNAPSHOT_CHUNK " + str(i+1) + "/" + str(total) + "\n"
        prompt += chunk + "\n"
        _write(out_dir / ("snapshot_chunk_" + str(i+1) + "_prompt.txt"), prompt)
        resp = call_gemini(prompt, timeout_s=900)
        _write(out_dir / ("snapshot_chunk_" + str(i+1) + "_response.txt"), resp)

def _call_gemini_diff(prompt: str, artifacts: Path, label: str) -> str:
    _step("gemini_call_begin label=" + label + " prompt_chars=" + str(len(prompt)))
    _step("gemini_prompt_preview label=" + label + " text=" + _preview(prompt))
    _step("gemini_prompt_file label=" + label + " path=" + str(artifacts / (label + "_prompt.txt")) )
    _write(artifacts / (label + "_prompt.txt"), prompt)
    resp = call_gemini(prompt, timeout_s=900)
    _write(artifacts / (label + "_response.txt"), resp)
    _step("gemini_response_preview label=" + label + " text=" + _preview(resp))
    _step("gemini_response_file label=" + label + " path=" + str(artifacts / (label + "_response.txt")) )
    _step("gemini_call_end label=" + label + " resp_chars=" + str(len(resp)))
    return resp

def _call_gemini_bundle(prompt: str, artifacts: Path, label: str) -> str:
    _step("gemini_call_begin label=" + label + " prompt_chars=" + str(len(prompt)))
    _step("gemini_prompt_preview label=" + label + " text=" + _preview(prompt))
    _step("gemini_prompt_file label=" + label + " path=" + str(artifacts / (label + "_prompt.txt")) )
    _write(artifacts / (label + "_prompt.txt"), prompt)
    resp = call_gemini(prompt, timeout_s=900)
    _write(artifacts / (label + "_response.txt"), resp)
    _step("gemini_response_preview label=" + label + " text=" + _preview(resp))
    _step("gemini_response_file label=" + label + " path=" + str(artifacts / (label + "_response.txt")) )
    _step("gemini_call_end label=" + label + " resp_chars=" + str(len(resp)))
    return resp

def _apply_file_bundle(bundle_text: str, repo_dir: Path, artifacts: Path, label: str) -> bool:
    t = (bundle_text or "").replace("\r\n","\n").replace("\r","\n")
    ls = t.split("\n")
    i = 0
    wrote = 0
    while i < len(ls):
        line = ls[i].strip()
        if line.startswith("FILE:"):
            path = line.split(":",1)[1].strip()
            i += 1
            if i >= len(ls) or ls[i].strip() != "<<<":
                _write(artifacts / (label + "_bundle_parse_fail.txt"), "missing <<< for " + path + "\n")
                return False
            i += 1
            content = []
            while i < len(ls) and ls[i].strip() != ">>>":
                content.append(ls[i])
                i += 1
            if i >= len(ls):
                _write(artifacts / (label + "_bundle_parse_fail.txt"), "missing >>> for " + path + "\n")
                return False
            i += 1
            outp = repo_dir / path
            outp.parent.mkdir(parents=True, exist_ok=True)
            outp.write_text("\n".join(content) + "\n", encoding="utf-8", errors="ignore")
            wrote += 1
            continue
        i += 1
    _write(artifacts / (label + "_bundle_applied.txt"), "files_written=" + str(wrote) + "\n")
    return wrote > 0

def _summarize_logs_short(logs_text: str) -> str:
    if not logs_text:
        return ""
    lines = logs_text.splitlines()
    pats = ["Traceback", "ERROR", "Error:", "FAILED", "FD_FAIL", "Exception"]
    hits = []
    for i, line in enumerate(lines):
        if any(p in line for p in pats):
            start = max(0, i - 2)
            end = min(len(lines), i + 6)
            hits.append("\n".join(lines[start:end]))
        if len(hits) >= 20:
            break
    head = "\n".join(lines[:80])
    tail = "\n".join(lines[-120:]) if len(lines) > 120 else "\n".join(lines)
    out = []
    out.append("HEAD\n" + head)
    out.append("TAIL\n" + tail)
    if hits:
        out.append("HITS\n" + "\n\n".join(hits))
    return "\n\n".join(out) + "\n"

def _read_workflow_yaml(repo_dir: Path, workflow_file: str, max_chars: int = 60000) -> str:
    p = repo_dir / ".github" / "workflows" / workflow_file
    if not p.exists():
        return ""
    txt = p.read_text(encoding="utf-8", errors="ignore")
    if len(txt) > max_chars:
        return txt[:max_chars] + "\n"
    return txt

def _extract_workflow_vars(yaml_text: str) -> Dict[str, List[str]]:
    # Lightweight extraction of referenced secrets/vars/env and inputs usage.
    out: Dict[str, List[str]] = {"secrets": [], "vars": [], "env": [], "inputs": []}
    if not yaml_text:
        return out

    def _add(k: str, v: str) -> None:
        if v and v not in out[k]:
            out[k].append(v)

    # secrets.NAME and vars.NAME references
    for m in re.finditer(r"\$\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}", yaml_text):
        _add("secrets", m.group(1))
    for m in re.finditer(r"\$\{\{\s*vars\.([A-Za-z0-9_]+)\s*\}\}", yaml_text):
        _add("vars", m.group(1))
    for m in re.finditer(r"\$\{\{\s*env\.([A-Za-z0-9_]+)\s*\}\}", yaml_text):
        _add("env", m.group(1))
    for m in re.finditer(r"\$\{\{\s*inputs\.([A-Za-z0-9_]+)\s*\}\}", yaml_text):
        _add("inputs", m.group(1))

    out["secrets"].sort()
    out["vars"].sort()
    out["env"].sort()
    out["inputs"].sort()
    return out

def _extract_workflow_dispatch_inputs(yaml_text: str, max_lines: int = 200) -> str:
    # Best-effort summary of workflow_dispatch inputs: name, required, default.
    if not yaml_text:
        return ""
    lines = yaml_text.splitlines()
    in_wd = False
    in_inputs = False
    current = ""
    required = ""
    default = ""
    out_lines: List[str] = []

    def _commit() -> None:
        nonlocal current, required, default
        if current:
            out_lines.append("- " + current + " required=" + (required or "") + " default=" + (default or ""))
        current = ""
        required = ""
        default = ""

    for raw in lines:
        s = raw.rstrip("\n")
        t = s.strip()

        if t.startswith("on:"):
            in_wd = False
            in_inputs = False
            _commit()

        if t == "workflow_dispatch:" or t.endswith(" workflow_dispatch:"):
            in_wd = True
            in_inputs = False
            _commit()
            continue

        if in_wd and t == "inputs:":
            in_inputs = True
            _commit()
            continue

        if not in_inputs:
            continue

        # inputs key
        if t.endswith(":") and not t.startswith(("required:", "default:", "description:", "type:", "options:")):
            _commit()
            current = t[:-1].strip()
            continue

        if t.startswith("required:"):
            required = t.split(":", 1)[1].strip()
            continue

        if t.startswith("default:"):
            default = t.split(":", 1)[1].strip().strip('"').strip("'")
            continue

        if len(out_lines) >= max_lines:
            break

    _commit()
    return "\n".join(out_lines).strip() + ("\n" if out_lines else "")

def _extract_failures(logs_text: str, max_items: int = 12) -> str:
    if not logs_text:
        return ""
    lines = logs_text.splitlines()
    pats = [
        "FD_FAIL",
        "FD_POLICY_FAIL",
        "Traceback",
        "ERROR",
        "Error:",
        "##[error]",
        "Process completed with exit code",
        "Unhandled exception",
    ]
    out: List[str] = []
    for i, line in enumerate(lines):
        if any(p in line for p in pats):
            start = max(0, i - 2)
            end = min(len(lines), i + 6)
            blk = "\n".join(lines[start:end]).strip()
            if blk and blk not in out:
                out.append(blk)
        if len(out) >= max_items:
            break
    return "\n\n".join(["-\n" + x for x in out]).strip() + ("\n" if out else "")

def _extract_failed_paths(git_apply_log: str) -> List[str]:
    paths: List[str] = []
    for line in (git_apply_log or "").splitlines():
        if "patch failed:" in line:
            # error: patch failed: path:line
            try:
                part = line.split("patch failed:",1)[1].strip()
                p = part.split(":",1)[0].strip()
                if p and p not in paths:
                    paths.append(p)
            except Exception:
                pass
        if line.startswith("Checking patch "):
            p = line.replace("Checking patch ","").strip().strip(".")
            if p and p not in paths:
                paths.append(p)
    return paths[:5]

def _read_repo_file(repo_dir: Path, rel_path: str, max_chars: int = 8000) -> str:
    p = repo_dir / rel_path
    if not p.exists():
        return ""
    txt = p.read_text(encoding="utf-8", errors="ignore")
    if len(txt) > max_chars:
        return txt[:max_chars] + "\n"
    return txt

def _normalize_diff(d: str) -> str:
    t = (d or "").replace("\r\n","\n").replace("\r","\n")
    if "diff --git" not in t:
        return t
    lines = t.split("\n")
    if not lines:
        return t
    # Ensure we have ---/+++ headers for git apply.
    # If the first diff block is missing them and jumps straight to @@, inject.
    m = re.match(r"^diff --git a/(.+) b/(.+)\s*$", lines[0].strip())
    if m:
        a_path = "a/" + m.group(1).strip()
        b_path = "b/" + m.group(2).strip()
        has_oldnew = any(l.startswith("--- ") for l in lines[:10]) and any(l.startswith("+++ ") for l in lines[:10])
        if not has_oldnew:
            # find insertion point after diff --git line
            ins = [lines[0], "--- " + a_path, "+++ " + b_path]
            rest = lines[1:]
            lines = ins + rest
    out = "\n".join(lines).strip() + "\n"
    return out

def _extract_diff(text: str) -> str:
    t = (text or "").replace("\r\n","\n").replace("\r","\n")
    idx = t.find("diff --git")
    if idx >= 0:
        d = t[idx:]
        d = _normalize_diff(d)
        return d
    # sometimes model returns '*** Begin Patch' - keep as fail if no diff.
    return ""

def _rerun_and_check(workflow_file: str, branch: str, inputs: Dict[str, str], actions_token: str, artifacts: Path, attempt: int, label: str) -> bool:
    _step("post_fix_rerun_begin label=" + label)
    start_epoch = time.time()
    dispatch_workflow(workflow_file, branch, inputs, actions_token)
    run_id = find_latest_run_id(workflow_file, branch, start_epoch - 5, actions_token, timeout_s=240)
    _step("post_fix_rerun_found run_id=" + str(run_id))
    info = wait_run_complete(run_id, actions_token, timeout_s=3600)
    status = str(info.get("status") or "")
    concl = str(info.get("conclusion") or "")
    _step("post_fix_rerun_completed run_id=" + str(run_id) + " status=" + status + " conclusion=" + concl)
    try:
        logs_zip = download_run_logs_zip(run_id, actions_token)
        logs_text = extract_logs_text(logs_zip, max_chars=200000)
        _write(artifacts / ("post_fix_run_" + str(run_id) + "_attempt_" + str(attempt) + ".log"), logs_text)
    except Exception:
        pass
    return (status == "completed" and concl == "success")

def main() -> int:
    if len(sys.argv) < 4:
        print("usage: fd_auto_tune_branch.py <branch> <workflow_file> <max_attempts> [workflow_inputs]")
        return 2
    branch = sys.argv[1].strip()
    workflow_file = sys.argv[2].strip()
    max_attempts = int((sys.argv[3].strip() or "5"))
    workflow_inputs = sys.argv[4] if len(sys.argv) > 4 else ""

    token = (os.environ.get("FD_BOT_TOKEN") or "").strip()
    actions_token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if token == "":
        raise RuntimeError("FD_FAIL: missing FD_BOT_TOKEN")
    if actions_token == "":
        raise RuntimeError("FD_FAIL: missing GITHUB_TOKEN")

    if max_attempts < 1:
        max_attempts = 1

    _step("tune_config branch=" + branch + " workflow_file=" + workflow_file + " max_attempts=" + str(max_attempts))

    artifacts = Path(tempfile.mkdtemp(prefix="fd_tune_artifacts_"))
    _write(artifacts / "branch.txt", branch + "\n")
    _write(artifacts / "workflow_file.txt", workflow_file + "\n")
    _write(artifacts / "workflow_inputs.txt", workflow_inputs + "\n")

    wt_dir, repo_root = _ensure_worktree(branch)
    _set_origin_with_token(repo_root, token)

    inputs = _parse_inputs(workflow_inputs)
    apply_err = ""
    apply_failed_context = ""

    for attempt in range(1, max_attempts + 1):
        _step("attempt_begin " + str(attempt) + "/" + str(max_attempts))
        try:
            # Dispatch target workflow
            start_epoch = time.time()
            _step("dispatch_workflow file=" + workflow_file + " ref=" + branch + " inputs=" + str(inputs))
            run_id = 0
            status = ""
            conclusion = ""
            html_url = ""
            logs_text = ""
            arts = []

            dispatch_failed = False
            dispatch_err = ""
            try:
                dispatch_workflow(workflow_file, branch, inputs, actions_token)
            except Exception:
                dispatch_failed = True
                dispatch_err = traceback.format_exc()
                logs_text = dispatch_err
                _write(artifacts / ("dispatch_failed_attempt_" + str(attempt) + ".log"), dispatch_err)

            if not dispatch_failed:
                run_id = find_latest_run_id(workflow_file, branch, start_epoch - 5, actions_token, timeout_s=180)
                _step("workflow_run_found run_id=" + str(run_id))
                run_info = wait_run_complete(run_id, actions_token, timeout_s=3600)
                status = str(run_info.get("status") or "")
                conclusion = str(run_info.get("conclusion") or "")
                html_url = str(run_info.get("html_url") or "")
                _step("workflow_run_completed run_id=" + str(run_id) + " status=" + status + " conclusion=" + conclusion)

                logs_zip = download_run_logs_zip(run_id, actions_token)
                logs_text = extract_logs_text(logs_zip, max_chars=350000)
                _write(artifacts / ("run_" + str(run_id) + "_attempt_" + str(attempt) + ".log"), logs_text)

                # Download run artifacts
                arts = list_run_artifacts(run_id, actions_token)
                _write(artifacts / ("run_" + str(run_id) + "_artifacts.json"), str(arts) + "\n")
                for a in arts:
                    aid = int(a.get("id") or 0)
                    name = str(a.get("name") or "artifact")
                    if aid <= 0:
                        continue
                    _step("download_artifact name=" + name + " id=" + str(aid))
                    blob = download_artifact_zip(aid, actions_token)
                    outp = artifacts / ("run_" + str(run_id) + "_artifact_" + name + ".zip")
                    outp.write_bytes(blob)

            if (not dispatch_failed) and status == "completed" and conclusion == "success":
                _step("green run_id=" + str(run_id))
                return 0

            # Prepare context: snapshot + logs + artifacts list
            snapshot_text = _read_latest_snapshot(wt_dir)
            _upload_snapshot_chunks(snapshot_text, artifacts / ("snapshot_upload_attempt_" + str(attempt)))

            wf_yaml = _read_workflow_yaml(Path(wt_dir), workflow_file)
            used = _extract_workflow_vars(wf_yaml)
            inputs_summary = _extract_workflow_dispatch_inputs(wf_yaml)

            contract_path = Path(wt_dir) / "fd_policy" / "auto_tune_contract.txt"
            contract_txt = _read_text_if_exists(contract_path)
            contract_hash = _sha256_text(contract_txt)[:12] if contract_txt.strip() != "" else ""
            repo_guide_txt = _read_repo_guide(Path(wt_dir))
            repo_guide_hash = _sha256_text(repo_guide_txt)[:12] if repo_guide_txt.strip() != "" else ""

            evidence_all = "\n".join([dispatch_err or "", logs_text or "", wf_yaml or "", apply_err or "", apply_failed_context or ""])
            failed_paths = sorted(set(_extract_failed_paths(evidence_all) + _extract_failed_paths(apply_err)))
            allowed_files = _compute_allowed_files(workflow_file, evidence_all, extra_paths=failed_paths)
            related_files = _expand_related_files(Path(wt_dir), allowed_files + failed_paths)
            related_ctx = _read_related_files_context(Path(wt_dir), related_files)
            prompt += "You are the Builder fixing an automated GitHub Actions workflow failure.\n"
            prompt += "\nGOAL\n"
            prompt += "Make the target workflow run succeed on the target branch with the smallest possible code change.\n"
            prompt += "\nHARD RULES\n"
            prompt += "- Output ONLY a standard unified diff (git apply compatible). No markdown. No explanations.\n"
            prompt += "- FIRST LINE MUST BE: diff --git a/FILE b/FILE\n"
            prompt += "- Make minimal changes required by evidence. No refactors, renames, or cleanup unless required by logs.\n"
            prompt += "- Do not change workflow triggers or secrets/vars/env names unless evidence explicitly requires it.\n"
            prompt += "- You MAY create new files if needed, but you must include them in the unified diff (new file mode + full content).\n"
            prompt += "- Prefer editing existing files over creating new files. Use REPO_GUIDE and RELATED_FILES to find existing code before adding new files.\n"
            prompt += "- If this workflow is used by automation, keep it dispatchable: must include on: workflow_dispatch.\n"
            prompt += "- Base everything on EVIDENCE below.\n"
            if contract_txt.strip() != "":
                prompt += "\nPROJECT_CONTRACT version=" + contract_hash + "\n" + contract_txt + "\n"
            if repo_guide_txt.strip() != "":
                prompt += "\nREPO_GUIDE version=" + repo_guide_hash + "\n" + repo_guide_txt + "\n"
            prompt += "\nALLOWED_FILES\n" + "\n".join(["- " + x for x in allowed_files]) + "\n"
            prompt += "\nTARGET\n"
            prompt += "branch: " + branch + "\n"
            prompt += "workflow_file: " + workflow_file + "\n"
            if run_id:
                prompt += "run_id: " + str(run_id) + "\n"
            if html_url:
                prompt += "run_url: " + html_url + "\n"
            if dispatch_failed:
                prompt += "dispatch: failed\n"
            else:
                prompt += "status: " + status + "\n"
                prompt += "conclusion: " + conclusion + "\n"

            if dispatch_failed:
                prompt += "\nEVIDENCE: DISPATCH_ERROR\n" + dispatch_err[:FD_PROMPT_MAX_LOG_CHARS] + "\n"

            prompt += "\nEVIDENCE: WORKFLOW_YAML_EXCERPT\n"
            prompt += wf_yaml[:FD_PROMPT_MAX_CTX_CHARS] + "\n"

            prompt += "\nEVIDENCE: VARIABLES_USED\n"
            prompt += "secrets: " + ",".join(used.get("secrets") or []) + "\n"
            prompt += "vars: " + ",".join(used.get("vars") or []) + "\n"
            prompt += "env: " + ",".join(used.get("env") or []) + "\n"
            prompt += "inputs_refs: " + ",".join(used.get("inputs") or []) + "\n"
            if inputs_summary.strip() != "":
                prompt += "workflow_dispatch_inputs:\n" + inputs_summary

            prompt += "\nEVIDENCE: FAILURES\n"
            fails = _extract_failures(logs_text)
            if fails.strip() == "":
                fails = "(no obvious failure markers found)\n"
            prompt += fails[:FD_PROMPT_MAX_LOG_CHARS] + "\n"

            if related_ctx.strip() != "":
                prompt += "\nEVIDENCE: RELATED_FILES\n" + related_ctx

            prompt += "\nEVIDENCE: WORKFLOW_LOGS_SUMMARY\n"
            summary = _summarize_logs_short(logs_text)
            prompt += summary[:FD_PROMPT_MAX_LOG_CHARS] + "\n"

            if apply_err.strip() != "":
                prompt += "\nEVIDENCE: PREVIOUS_GIT_APPLY_ERROR\n" + apply_err + "\n"
            if apply_failed_context.strip() != "":
                prompt += "\nEVIDENCE: CURRENT_FILE_CONTEXT\n" + apply_failed_context[:FD_PROMPT_MAX_CTX_CHARS] + "\n"

            prompt += "\nEVIDENCE: RUN_ARTIFACTS\n"
            prompt += str([str(x.get("name") or "") for x in arts]) + "\n"

            diff_text = _call_gemini_diff(prompt, artifacts, "fix_attempt_" + str(attempt))
            ok_fmt, reason_fmt = _validate_unified_diff_only(diff_text)
            if not ok_fmt:
                _write(artifacts / ("fix_format_violation_attempt_" + str(attempt) + ".txt"), reason_fmt + "\n" + diff_text[:8000] + "\n")
                _step("format_violation attempt=" + str(attempt) + " reason=" + reason_fmt)
                apply_err = "FD_FAIL: " + reason_fmt
                continue

            diff = _extract_diff(diff_text)
            if diff.strip() == "":
                _write(artifacts / ("fix_diff_missing_attempt_" + str(attempt) + ".txt"), diff_text[:8000] + "\n")
                _step("diff_missing attempt=" + str(attempt))
                apply_err = "FD_FAIL: gemini did not return unified diff"
                continue

            ok_scope, reason_scope = _validate_scope(diff, allowed_files)
            if not ok_scope:
                _write(artifacts / ("fix_scope_violation_attempt_" + str(attempt) + ".txt"), reason_scope + "\n" + diff[:8000] + "\n")
                _step("scope_violation attempt=" + str(attempt) + " reason=" + reason_scope)
                apply_err = "FD_FAIL: " + reason_scope
                continue

            flips = _detect_secret_var_flips(diff)
            if flips:
                ev = (fails or "") + "\n" + (dispatch_err or "") + "\n" + (summary or "")
                blocked = []
                for direction, key, fpath in flips:
                    if key not in ev:
                        blocked.append(direction + ":" + key + "@" + fpath)
                if blocked:
                    msg = "stability_violation: secrets/vars flip not justified by evidence: " + ",".join(blocked)
                    _write(artifacts / ("fix_stability_violation_attempt_" + str(attempt) + ".txt"), msg + "\n" + diff[:8000] + "\n")
                    _step("stability_violation attempt=" + str(attempt))
                    apply_err = "FD_FAIL: " + msg
                    continue

            ok_req, reason_req = _validate_requirements_install(Path(wt_dir), diff)
            if not ok_req:
                _write(artifacts / ("fix_stability_violation_requirements_attempt_" + str(attempt) + ".txt"), reason_req + "\n" + diff[:8000] + "\n")
                _step("stability_violation attempt=" + str(attempt))
                apply_err = "FD_FAIL: " + reason_req
                continue

            diff_path = artifacts / ("fix_attempt_" + str(attempt) + ".diff")
            if not diff.endswith("\n"):
                diff = diff + "\n"
            _write(diff_path, diff)

            # Pre-check diff application (deterministic)
            chk = _run(["git","apply","--check","--whitespace=nowarn", str(diff_path)], str(wt_dir))
            _write(artifacts / ("git_apply_check_attempt_" + str(attempt) + ".log"), chk.stdout)
            if chk.returncode != 0:
                apply_err = chk.stdout[:4000]
                _step("git_apply_check_failed attempt=" + str(attempt))
                continue

            # Apply diff in worktree
            app = _run(["git","apply","--3way","--whitespace=nowarn", str(diff_path)], str(wt_dir))
            _write(artifacts / ("git_apply_attempt_" + str(attempt) + ".log"), app.stdout)
            if app.returncode != 0:
                apply_err = app.stdout[:4000]
                paths = _extract_failed_paths(app.stdout)
                ctx_parts = []
                for p in paths:
                    ctx_parts.append("FILE_CURRENT_BEGIN " + p + "\n" + _read_repo_file(Path(wt_dir), p) + "FILE_CURRENT_END " + p + "\n")
                apply_failed_context = "\n".join(ctx_parts)
                _write(artifacts / ("git_apply_failed_context_attempt_" + str(attempt) + ".txt"), apply_failed_context)
                _step("git_apply_failed attempt=" + str(attempt))
                continue
            _step("git_apply_ok attempt=" + str(attempt))
            _cleanup_pycache(Path(wt_dir), artifacts, "attempt_" + str(attempt))

            subprocess.check_call(["git","add","-A"], cwd=str(wt_dir))
            try:
                subprocess.check_call(["git","commit","-m","FD tune attempt " + str(attempt)], cwd=str(wt_dir))
            except Exception:
                pass
            push = _push_with_fallback(Path(wt_dir), repo_root, artifacts, "git_push_attempt_" + str(attempt), token, actions_token)
            if push.returncode != 0:
                _step("git_push_failed attempt=" + str(attempt))
                continue
            _step("git_push_ok attempt=" + str(attempt))
            ok = _rerun_and_check(workflow_file, branch, inputs, actions_token, artifacts, attempt, "attempt_" + str(attempt))
            if ok:
                _step("post_fix_green attempt=" + str(attempt))
                return 0
            _step("post_fix_still_red attempt=" + str(attempt))
            apply_err = ""
            apply_failed_context = ""
        except Exception:
            msg = traceback.format_exc()
            if "FD_GEMINI_QUOTA_EXCEEDED" in msg:
                _write(artifacts / "FD_GEMINI_BLOCKED.txt", msg + "\n")
                _step("gemini_quota_exceeded")
                return 3
            _write(artifacts / ("unexpected_exception_attempt_" + str(attempt) + ".txt"), msg + "\n")
            _step("attempt_exception attempt=" + str(attempt))
            print(msg)
            continue

    _step("tuning_attempts_exhausted")
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
