from typing import List, Tuple
from dataclasses import dataclass

@dataclass
class FileEntry:
    path: str
    content: str

@dataclass
class Patch:
    kind: str  # patch | bundle
    work_item_id: str
    producer_role: str
    files: List[FileEntry]
    delete: List[str]

def _fail(msg: str) -> None:
    raise ValueError("FD_PARSE_FAIL: " + msg)

def parse_fd_patch_v1(text: str) -> Patch:
    t = (text or "").replace("\r\n","\n").replace("\r","\n").strip()
    if not t.startswith("FD_PATCH_V1"):
        _fail("missing FD_PATCH_V1 header")
    lines = t.split("\n")
    meta = {}
    files: List[FileEntry] = []
    delete: List[str] = []
    i = 1
    while i < len(lines):
        line = lines[i]
        if line.startswith("FILE:") or line.strip() in ("DELETE:", "END"):
            break
        if line.strip() == "":
            i += 1
            continue
        if ":" not in line:
            _fail("bad meta line: " + line[:120])
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip()
        i += 1

    def parse_file(j: int) -> Tuple[int, FileEntry]:
        header = lines[j]
        path = header[len("FILE:"):].strip()
        if path == "":
            _fail("empty FILE path")
        if j + 1 >= len(lines) or lines[j+1].strip() != "<<<":
            _fail("FILE missing <<< for path=" + path)
        k = j + 2
        buf = []
        while k < len(lines):
            if lines[k].strip() == ">>>":
                break
            buf.append(lines[k])
            k += 1
        if k >= len(lines):
            _fail("FILE missing >>> for path=" + path)
        return k + 1, FileEntry(path=path, content="\n".join(buf) + "\n")

    while i < len(lines):
        line = lines[i].strip()
        if line == "":
            i += 1
            continue
        if line.startswith("FILE:"):
            i, fe = parse_file(i)
            files.append(fe)
            continue
        if line == "DELETE:":
            i += 1
            while i < len(lines):
                l = lines[i].strip()
                if l == "":
                    i += 1
                    continue
                if l == "END":
                    break
                if l.startswith("-"):
                    delete.append(l[1:].strip())
                else:
                    _fail("bad DELETE line: " + l[:120])
                i += 1
            continue
        if line == "END":
            break
        _fail("unexpected line: " + line[:120])

    wi = meta.get("work_item_id","").strip()
    prod = meta.get("producer_role","").strip()
    if wi == "":
        wi = "WI-AUTO-TUNE"
    if prod == "":
        prod = "BUILDER"
    if not files:
        _fail("no FILE blocks")
    return Patch(kind="patch", work_item_id=wi, producer_role=prod, files=files, delete=delete)

def bundle_total_parts(raw: str) -> Tuple[int, int]:
    t = (raw or "").strip()
    if not t.startswith("FD_BUNDLE_V1"):
        return (1,1)
    first = t.splitlines()[0].strip()
    if "PART" not in first:
        return (1,1)
    toks = first.split()
    if len(toks) < 4:
        return (1,1)
    frac = toks[3]
    if "/" not in frac:
        return (1,1)
    a,b = frac.split("/",1)
    try:
        return (int(a), int(b))
    except Exception:
        return (1,1)

def _strip_bundle_header(raw: str) -> str:
    t = (raw or "").replace("\r\n","\n").replace("\r","\n").strip()
    if not t.startswith("FD_BUNDLE_V1"):
        _fail("bundle missing header")
    lines = t.split("\n")
    return "\n".join(lines[1:]).lstrip()

def parse_bundle_parts(parts: List[str]) -> Patch:
    if not parts:
        _fail("no parts")
    base: Patch | None = None
    seen = {}
    order: List[str] = []
    delete: List[str] = []
    for raw in parts:
        patch_text = "FD_PATCH_V1\n" + _strip_bundle_header(raw)
        p = parse_fd_patch_v1(patch_text)
        if base is None:
            base = p
        delete.extend(p.delete)
        for fe in p.files:
            if fe.path not in order:
                order.append(fe.path)
            seen[fe.path] = fe
    assert base is not None
    merged = [seen[p] for p in order]
    return Patch(kind="bundle", work_item_id=base.work_item_id, producer_role=base.producer_role, files=merged, delete=delete)
