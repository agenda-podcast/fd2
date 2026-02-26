from dataclasses import dataclass
from typing import List, Optional

SCHEMA_VERSION = "FD-ARTIFACT-1.0"

@dataclass
class FileEntry:
    path: str
    content: str
    content_type: str = "text/plain"
    encoding: str = "utf-8"

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
