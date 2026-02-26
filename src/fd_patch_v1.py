import os
from typing import Dict, List, Tuple

from src.fd_types import ArtifactManifest, FileEntry, SCHEMA_VERSION

def _fail(msg: str) -> None:
    raise ValueError("FD_PATCH_V1 parse failed: " + msg)

def _guess_content_type(path: str) -> str:
    p = path.lower()
    if p.endswith(".py"):
        return "text/x-python"
    if p.endswith(".md"):
        return "text/markdown"
    if p.endswith(".yml") or p.endswith(".yaml"):
        return "text/yaml"
    if p.endswith(".json"):
        return "application/json"
    if p.endswith(".js"):
        return "text/javascript"
    if p.endswith(".html"):
        return "text/html"
    if p.endswith(".css"):
        return "text/css"
    return "text/plain"

def load_manifest_from_patch_text(text: str) -> ArtifactManifest:
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = t.split("\n")
    if not lines or lines[0].strip() != "FD_PATCH_V1":
        _fail("missing FD_PATCH_V1 header")

    meta: Dict[str, str] = {}
    files: List[FileEntry] = []
    delete: List[str] = []
    verification_steps: List[str] = []

    i = 1
    # metadata until FILE: or DELETE: or END
    while i < len(lines):
        line = lines[i]
        if line.startswith("FILE:") or line.startswith("DELETE:") or line.strip() == "END":
            break
        if line.strip() == "":
            i += 1
            continue
        if ":" not in line:
            _fail("invalid metadata line: " + line[:120])
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip()
        i += 1

    def parse_file_block(start_i: int) -> Tuple[int, FileEntry]:
        header = lines[start_i]
        if not header.startswith("FILE:"):
            _fail("expected FILE: got " + header[:120])
        path = header[len("FILE:"):].strip()
        if path == "":
            _fail("empty FILE path")
        if start_i + 1 >= len(lines) or lines[start_i + 1].strip() != "<<<":
            _fail("FILE missing <<< for path=" + path)
        j = start_i + 2
        buf: List[str] = []
        while j < len(lines):
            if lines[j].strip() == ">>>":
                break
            buf.append(lines[j])
            j += 1
        if j >= len(lines):
            _fail("FILE missing >>> for path=" + path)
        content = "\n".join(buf) + "\n"
        fe = FileEntry(
            path=path,
            content=content,
            content_type=_guess_content_type(path),
            encoding="utf-8",
        )
        return j + 1, fe

    while i < len(lines):
        line = lines[i].strip()
        if line == "":
            i += 1
            continue
        if line.startswith("FILE:"):
            i, fe = parse_file_block(i)
            files.append(fe)
            continue
        if line == "DELETE:":
            i += 1
            while i < len(lines):
                l = lines[i].strip()
                if l == "" :
                    i += 1
                    continue
                if l == "END":
                    break
                if l.startswith("-"):
                    delete.append(l[1:].strip())
                else:
                    _fail("invalid DELETE line: " + l[:120])
                i += 1
            continue
        if line == "VERIFY:":
            i += 1
            while i < len(lines):
                l = lines[i].strip()
                if l == "":
                    i += 1
                    continue
                if l == "END":
                    break
                if l.startswith("-"):
                    verification_steps.append(l[1:].strip())
                else:
                    _fail("invalid VERIFY line: " + l[:120])
                i += 1
            continue
        if line == "END":
            break
        _fail("unexpected line: " + line[:120])

    if not files:
        _fail("no FILE blocks found")

    work_item_id = meta.get("work_item_id", "")
    producer_role = meta.get("producer_role", "")
    artifact_type = meta.get("artifact_type", "repo_patch")
    if work_item_id == "":
        _fail("missing work_item_id")
    if producer_role == "":
        _fail("missing producer_role")
    if artifact_type == "":
        _fail("missing artifact_type")

    return ArtifactManifest(
        schema_version=SCHEMA_VERSION,
        work_item_id=work_item_id,
        producer_role=producer_role,
        artifact_type=artifact_type,
        files=files,
        delete=delete,
        entry_point=meta.get("entry_point") or None,
        build_command=meta.get("build_command") or None,
        test_command=meta.get("test_command") or None,
        verification_steps=verification_steps,
        notes="",
    )
