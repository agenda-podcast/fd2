#!/usr/bin/env python3
import os
from pathlib import Path

TEXT_EXT = {".py",".md",".yml",".yaml",".json",".txt",".html",".css",".js",".ts",".csv"}

def _fail(msg: str) -> None:
    raise RuntimeError("FD_FAIL: " + msg)

def _is_text_path(rel: str) -> bool:
    return Path(rel).suffix.lower() in TEXT_EXT

def apply_snapshot(snapshot_text: str, repo_root: Path) -> None:
    t = (snapshot_text or "").replace("\r\n","\n").replace("\r","\n")
    if not t.strip().startswith("FD_APP_SOURCE_V1"):
        _fail("snapshot missing header")
    lines = t.split("\n")
    i = 0
    # skip header/meta until first FILE:
    while i < len(lines) and not lines[i].startswith("FILE:"):
        i += 1
    while i < len(lines):
        line = lines[i]
        if not line.startswith("FILE:"):
            i += 1
            continue
        rel = line.split(":",1)[1].strip()
        if rel == "":
            _fail("empty FILE path")
        if i+1 >= len(lines) or lines[i+1].strip() != "<<<":
            _fail("missing <<< for " + rel)
        j = i + 2
        buf = []
        while j < len(lines):
            if lines[j].strip() == ">>>":
                break
            buf.append(lines[j])
            j += 1
        if j >= len(lines):
            _fail("missing >>> for " + rel)
        i = j + 1
        if not _is_text_path(rel):
            continue
        out_path = repo_root / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(buf) + "\n", encoding="utf-8")

def main() -> int:
    import sys
    if len(sys.argv) < 2:
        print("usage: fd_auto_apply_snapshot.py <snapshot_file>")
        return 2
    repo_root = Path(os.getcwd())
    snap = Path(sys.argv[1])
    if not snap.exists():
        _fail("snapshot file not found " + str(snap))
    txt = snap.read_text(encoding="utf-8", errors="ignore")
    apply_snapshot(txt, repo_root)
    print("FD_OK: applied snapshot")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
