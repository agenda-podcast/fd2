import json

from src.fd_types import ArtifactManifest, FileEntry, SCHEMA_VERSION
from src.fd_patch_v1 import load_manifest_from_patch_text
from src.fd_bundle_v1 import parse_bundle_parts

def _as_str(x) -> str:
    if x is None:
        return ""
    return str(x)

def load_manifest_from_text(text: str) -> ArtifactManifest:
    t = (text or "").strip()
    if t == "":
        raise ValueError("empty manifest text")

    if t.startswith("```"):
        # remove code fences if present
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()

    if t.startswith("FD_BUNDLE_V1"):
        return parse_bundle_parts([t])
    if t.startswith("FD_PATCH_V1"):
        return load_manifest_from_patch_text(t)

    # JSON path (backward compatible)
    try:
        obj = json.loads(t)
    except Exception:
        # attempt to extract first json object block
        start = t.find("{")
        end = t.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        obj = json.loads(t[start:end+1])

    schema = _as_str(obj.get("schema_version", SCHEMA_VERSION))
    wi = _as_str(obj.get("work_item_id", ""))
    prod = _as_str(obj.get("producer_role", ""))
    art = _as_str(obj.get("artifact_type", "repo_patch"))

    files = []
    for f in obj.get("files", []) or []:
        files.append(FileEntry(
            path=_as_str(f.get("path", "")),
            content=_as_str(f.get("content", "")),
            content_type=_as_str(f.get("content_type", "text/plain")),
            encoding=_as_str(f.get("encoding", "utf-8")),
        ))

    delete = [str(x) for x in (obj.get("delete", []) or [])]
    entry_point = obj.get("entry_point")
    build_command = obj.get("build_command")
    test_command = obj.get("test_command")
    verification_steps = [str(x) for x in (obj.get("verification_steps", []) or [])]
    notes = _as_str(obj.get("notes", ""))

    if wi == "":
        raise ValueError("missing work_item_id")
    if prod == "":
        raise ValueError("missing producer_role")

    return ArtifactManifest(
        schema_version=schema,
        work_item_id=wi,
        producer_role=prod,
        artifact_type=art,
        files=files,
        delete=delete,
        entry_point=entry_point,
        build_command=build_command,
        test_command=test_command,
        verification_steps=verification_steps,
        notes=notes,
    )
