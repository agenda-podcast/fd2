import base64
import os
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
    for p in manifest.delete:
        full = os.path.join(repo_root, p)
        if os.path.exists(full):
            os.remove(full)

    for fe in manifest.files:
        _write_file(repo_root, fe)

def _write_file(repo_root: str, fe: FileEntry) -> None:
    if fe.path.strip() == "" or fe.path.startswith("../") or fe.path.startswith("..\"):
        raise ValueError("invalid path")
    full = os.path.join(repo_root, fe.path)
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
