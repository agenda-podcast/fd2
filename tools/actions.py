#!/usr/bin/env python3
"""Deterministic repo actions for FD agents (no LLM).

ASCII-only, <= 500 lines.

Action types:
- write_file: write a text file
- append_file: append text to a file (creates if missing)
- replace_regex: regex replace in a file (first match or all)
- mkdir: create directory
- touch: create empty file if missing
- add_nav_item: add an item to docs/nav.json
- ensure_line: ensure a line exists in a file

All content written must be ASCII-only.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ActionResult:
    changed_paths: List[str]
    notes: List[str]


def ensure_ascii(s: str) -> None:
    s.encode("ascii")


def _read_text(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def _write_text(path: str, content: str) -> None:
    ensure_ascii(content)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def _append_text(path: str, content: str) -> None:
    ensure_ascii(content)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(content)


def action_write_file(a: Dict[str, Any]) -> ActionResult:
    path = str(a["path"])
    content = str(a.get("content", ""))
    _write_text(path, content if content.endswith("\n") else content + "\n")
    return ActionResult([path], ["write_file ok"])


def action_append_file(a: Dict[str, Any]) -> ActionResult:
    path = str(a["path"])
    content = str(a.get("content", ""))
    _append_text(path, content if content.endswith("\n") else content + "\n")
    return ActionResult([path], ["append_file ok"])


def action_replace_regex(a: Dict[str, Any]) -> ActionResult:
    path = str(a["path"])
    pattern = str(a["pattern"])
    repl = str(a["replacement"])
    multiple = bool(a.get("multiple", False))

    # Guard: reject patterns with known ReDoS structures (nested quantifiers)
    if len(pattern) > 256:
        raise ValueError("replace_regex pattern too long (max 256 chars)")

    txt = _read_text(path)
    if not txt:
        raise ValueError("replace_regex target missing or empty: %s" % path)

    flags = re.DOTALL
    if multiple:
        new = re.sub(pattern, repl, txt, flags=flags)
    else:
        new = re.sub(pattern, repl, txt, count=1, flags=flags)

    if new == txt:
        return ActionResult([], ["replace_regex no-op"])
    _write_text(path, new)
    return ActionResult([path], ["replace_regex ok"])


def action_mkdir(a: Dict[str, Any]) -> ActionResult:
    path = str(a["path"])
    os.makedirs(path, exist_ok=True)
    return ActionResult([path], ["mkdir ok"])


def action_touch(a: Dict[str, Any]) -> ActionResult:
    path = str(a["path"])
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not os.path.exists(path):
        _write_text(path, "")
        return ActionResult([path], ["touch created"])
    return ActionResult([], ["touch exists"])


def action_add_nav_item(a: Dict[str, Any]) -> ActionResult:
    nav_path = str(a.get("nav_path", "docs/nav.json"))
    item_id = str(a["id"])
    title = str(a["title"])
    page_path = str(a["path"])

    raw = _read_text(nav_path)
    if not raw:
        raise ValueError("docs/nav.json missing")
    nav = json.loads(raw)

    for it in nav:
        if it.get("id") == item_id:
            return ActionResult([], ["nav item exists"])

    nav.append({"id": item_id, "title": title, "path": page_path})
    out = json.dumps(nav, indent=2) + "\n"
    ensure_ascii(out)
    _write_text(nav_path, out)
    return ActionResult([nav_path], ["nav item added"])


def action_ensure_line(a: Dict[str, Any]) -> ActionResult:
    path = str(a["path"])
    line = str(a["line"])
    ensure_ascii(line)

    txt = _read_text(path)
    if line in txt.splitlines():
        return ActionResult([], ["ensure_line exists"])
    if txt and not txt.endswith("\n"):
        txt += "\n"
    txt += line + "\n"
    _write_text(path, txt)
    return ActionResult([path], ["ensure_line added"])


ACTION_MAP = {
    "write_file": action_write_file,
    "append_file": action_append_file,
    "replace_regex": action_replace_regex,
    "mkdir": action_mkdir,
    "touch": action_touch,
    "add_nav_item": action_add_nav_item,
    "ensure_line": action_ensure_line,
}


def run_actions(actions: List[Dict[str, Any]]) -> ActionResult:
    changed: List[str] = []
    notes: List[str] = []
    for a in actions:
        t = str(a.get("type", "")).strip()
        if t not in ACTION_MAP:
            raise ValueError("Unsupported action type: %s" % t)
        res = ACTION_MAP[t](a)
        changed.extend(res.changed_paths)
        notes.extend(res.notes)
    # dedupe
    changed = sorted(set(changed))
    return ActionResult(changed_paths=changed, notes=notes)
