import os
import zipfile
from typing import List, Optional

def zip_dir(src_dir: str, zip_path: str, exclude_prefixes: Optional[List[str]] = None) -> None:
    excl = exclude_prefixes or []
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirnames, filenames in os.walk(src_dir):
            if ".git" in dirnames:
                dirnames.remove(".git")
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, src_dir).replace(os.sep, "/")
                skip = False
                for pfx in excl:
                    if rel.startswith(pfx):
                        skip = True
                        break
                if skip:
                    continue
                z.write(full, rel)
