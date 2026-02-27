import shutil
from pathlib import Path
from src.fd_auto.patch_parse import Patch

def apply_patch(patch: Patch, repo_root: str) -> None:
    root = Path(repo_root)
    for rel in patch.delete:
        if rel.strip() == "":
            continue
        p = root / rel
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            try:
                p.unlink()
            except Exception:
                pass
    for fe in patch.files:
        path = root / fe.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(fe.content, encoding="utf-8")
