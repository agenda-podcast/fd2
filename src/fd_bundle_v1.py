from typing import List, Tuple

from src.fd_patch_v1 import load_manifest_from_patch_text
from src.fd_types import ArtifactManifest, FileEntry

def bundle_total_parts(raw: str) -> Tuple[int, int]:
    t = (raw or "").strip()
    if not t.startswith("FD_BUNDLE_V1"):
        return (1, 1)
    first = t.splitlines()[0].strip()
    if "PART" not in first:
        return (1, 1)
    toks = first.split()
    if len(toks) < 4:
        return (1, 1)
    frac = toks[3]
    if "/" not in frac:
        return (1, 1)
    a, b = frac.split("/", 1)
    try:
        return (int(a), int(b))
    except Exception:
        return (1, 1)

def _strip_header(raw: str) -> str:
    t = (raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not t.startswith("FD_BUNDLE_V1"):
        raise ValueError("missing FD_BUNDLE_V1")
    lines = t.split("\n")
    return "\n".join(lines[1:]).lstrip()

def parse_bundle_parts(parts: List[str]) -> ArtifactManifest:
    if not parts:
        raise ValueError("no parts")
    base: ArtifactManifest | None = None
    seen = {}
    order: List[str] = []
    delete: List[str] = []
    for raw in parts:
        patch_text = "FD_PATCH_V1\n" + _strip_header(raw)
        m = load_manifest_from_patch_text(patch_text)
        if base is None:
            base = m
        delete.extend(m.delete or [])
        for fe in m.files:
            if fe.path not in order:
                order.append(fe.path)
            seen[fe.path] = fe
    assert base is not None
    merged_files: List[FileEntry] = [seen[p] for p in order]
    return ArtifactManifest(
        schema_version=base.schema_version,
        work_item_id=base.work_item_id,
        producer_role=base.producer_role,
        artifact_type=base.artifact_type,
        files=merged_files,
        delete=delete,
        entry_point=base.entry_point,
        build_command=base.build_command,
        test_command=base.test_command,
        verification_steps=base.verification_steps,
        notes="",
    )
