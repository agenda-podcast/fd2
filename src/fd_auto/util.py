import os
import re
from typing import Dict, Tuple

def env(name: str, default: str = "") -> str:
    v = os.environ.get(name, default)
    return (v or "").strip()

def require_env(name: str) -> str:
    v = env(name)
    if v == "":
        raise RuntimeError("FD_FAIL: missing env " + name)
    return v

def extract_field(text: str, key: str) -> str:
    for line in (text or "").splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return ""

def slugify(s: str) -> str:
    t = (s or "").lower().strip()
    t = re.sub(r"[^a-z0-9]+", "-", t)
    t = re.sub(r"-+", "-", t).strip("-")
    if t == "":
        return "app"
    return t[:40]

def task_key(s: str) -> Tuple[int, int, int, int, int, int, int, int]:
    t = (s or "").strip()
    if not re.match(r"^[0-9]+(\.[0-9]+)*$", t):
        return (9999, 9999, 9999, 9999, 9999, 9999, 9999, 9999)
    parts = [int(x) for x in t.split(".")]
    pad = 8
    parts = parts[:pad] + [9999] * max(0, pad - len(parts))
    return tuple(parts)

def first_n_lines(s: str, n: int) -> str:
    return "\n".join((s or "").splitlines()[:n])
