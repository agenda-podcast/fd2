import json
import os
import subprocess
from typing import List, Tuple

def run(cmd: List[str]) -> None:
    subprocess.check_call(cmd)

def gh_release_create(tag: str, title: str, notes: str, assets: List[str]) -> None:
    cmd = ["gh", "release", "create", tag, "--title", title, "--notes", notes]
    cmd.extend(assets)
    run(cmd)

def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

def write_json(path: str, obj) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")
