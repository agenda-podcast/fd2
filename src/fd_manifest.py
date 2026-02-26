import json
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

SCHEMA_VERSION = "FD-ARTIFACT-1.0"

@dataclass
class FileEntry:
    path: str
    content: str
    content_type: str
    encoding: str

@dataclass
class ArtifactManifest:
    schema_version: str
    work_item_id: str
    producer_role: str
    artifact_type: str
    files: List[FileEntry]
    delete: List[str]
    entry_point: Optional[str]
    build_command: Optional[str]
    test_command: Optional[str]
    verification_steps: List[str]
    notes: str

def parse_manifest(obj: Dict[str, Any]) -> ArtifactManifest:
    if obj.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("schema_version mismatch")
    if obj.get("notes", "") != "":
        raise ValueError("notes must be empty string")
    files_raw = obj.get("files")
    if not isinstance(files_raw, list) or len(files_raw) == 0:
        raise ValueError("files must be a non-empty array")
    files: List[FileEntry] = []
    for fe in files_raw:
        files.append(FileEntry(
            path=str(fe.get("path","")),
            content=str(fe.get("content","")),
            content_type=str(fe.get("content_type","")),
            encoding=str(fe.get("encoding",""))
        ))
    delete_raw = obj.get("delete", [])
    if not isinstance(delete_raw, list):
        raise ValueError("delete must be an array")
    vs = obj.get("verification_steps", [])
    if not isinstance(vs, list):
        raise ValueError("verification_steps must be an array")
    return ArtifactManifest(
        schema_version=obj["schema_version"],
        work_item_id=str(obj.get("work_item_id","")),
        producer_role=str(obj.get("producer_role","")),
        artifact_type=str(obj.get("artifact_type","")),
        files=files,
        delete=[str(x) for x in delete_raw],
        entry_point=obj.get("entry_point"),
        build_command=obj.get("build_command"),
        test_command=obj.get("test_command"),
        verification_steps=[str(x) for x in vs],
        notes=obj.get("notes","")
    )

def load_manifest_from_text(text: str) -> ArtifactManifest:
    t = (text or "").strip()
    if t == "":
        raise ValueError("manifest text is empty")
    # Some models may wrap JSON in code fences or prepend small prefixes.
    if t.startswith("```"):
        lines = t.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
            t = "\n".join(lines[1:-1]).strip()
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        # Best-effort extraction: parse the first JSON object in the output.
        start = t.find("{")
        end = t.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("manifest JSON not found in model output")
        obj = json.loads(t[start:end+1])
    if not isinstance(obj, dict):
        raise ValueError("manifest is not a JSON object")
    return parse_manifest(obj)
