#!/usr/bin/env python3
import datetime
import os
from pathlib import Path

TEXT_EXT = {".py",".md",".yml",".yaml",".json",".txt",".html",".css",".js",".ts",".csv"}

EXCLUDE_DIRS = {".git","__pycache__",".pytest_cache","node_modules",".venv","venv","docs/_site",".github"}

def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXT

def _rel(p: Path, root: Path) -> str:
    return str(p.relative_to(root)).replace("\\","/")

def _should_skip_dir(rel: str) -> bool:
    for x in EXCLUDE_DIRS:
        if rel == x or rel.startswith(x + "/"):
            return True
    return False

def main() -> int:
    repo_root = Path(os.getcwd())
    out_dir = repo_root / "docs" / "assets" / "app"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / ("app-source_" + ts + ".txt")

    max_file_bytes = int(os.environ.get("FD_SNAPSHOT_MAX_FILE_BYTES","600000") or "600000")

    lines = []
    lines.append("FD_APP_SOURCE_V1")
    lines.append("timestamp_utc: " + ts)
    lines.append("root: /")
    lines.append("")

    for dp, dn, fn in os.walk(repo_root):
        rel_dir = _rel(Path(dp), repo_root)
        if rel_dir == ".":
            rel_dir = ""
        if _should_skip_dir(rel_dir):
            dn[:] = []
            continue
        dn[:] = [d for d in dn if not _should_skip_dir((rel_dir + "/" + d).strip("/"))]
        for f in fn:
            p = Path(dp) / f
            rel = _rel(p, repo_root)
            if rel.startswith("docs/assets/app/app-source_"):
                continue
            if not _is_text_file(p):
                continue
            try:
                if p.stat().st_size > max_file_bytes:
                    continue
            except Exception:
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            lines.append("FILE: " + rel)
            lines.append("<<<")
            lines.extend(content.replace("\r\n","\n").replace("\r","\n").split("\n"))
            if not content.endswith("\n"):
                lines.append("")
            lines.append(">>>")
            lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print("FD_OK: wrote " + str(out_path))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
