import base64
import os
import shutil
from typing import List
from .fd_manifest import ArtifactManifest, FileEntry

TEXT_ENCODINGS = {"utf-8"}
BINARY_ENCODINGS = {"base64"}

def ensure_ascii_text(s: str) -> None:
    try:
        s.encode("ascii")
    except UnicodeEncodeError as e:
        raise ValueError("non-ascii content detected") from e

def apply_manifest(manifest: ArtifactManifest, repo_root: str) -> None:
    root_real = os.path.realpath(repo_root)

    for p in manifest.delete:
        full = _safe_join(root_real, p)
        if os.path.isdir(full):
            shutil.rmtree(full)
        elif os.path.exists(full):
            os.remove(full)

    for fe in manifest.files:
        _write_file(repo_root, fe)

def _write_file(repo_root: str, fe: FileEntry) -> None:
    full = _safe_join(os.path.realpath(repo_root), fe.path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    if fe.encoding in TEXT_ENCODINGS:
        ensure_ascii_text(fe.content)
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(fe.content)
        return
    if fe.encoding in BINARY_ENCODINGS:
        raw = base64.b64decode(fe.content.encode("utf-8"))
        with open(full, "wb") as f:
            f.write(raw)
        return
    raise ValueError("unsupported encoding")


def _safe_join(root_real: str, rel_path: str) -> str:
    p = (rel_path or "").strip()
    if p == "":
        raise ValueError("invalid path")

    # Normalize separators to simplify checks.
    p = p.replace("\\", "/")
    if p.startswith("/"):
        raise ValueError("invalid path")

    norm = os.path.normpath(p)
    if norm == ".." or norm.startswith(".." + os.sep) or norm.startswith(".."):
        raise ValueError("invalid path")
    if os.path.isabs(norm):
        raise ValueError("invalid path")

    full = os.path.realpath(os.path.join(root_real, norm))
    if not (full == root_real or full.startswith(root_real + os.sep)):
        raise ValueError("invalid path")
    return full
