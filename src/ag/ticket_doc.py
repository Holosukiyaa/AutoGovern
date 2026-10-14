"""Canonical `.data/ticket.md` is the only intent document for a task.

`## 意图` stays as written. Start seals red lines into `## 红线` and `.data/redlines.copy`.
Start, verify, and finish rewrite only `## 现场`.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .managed import ChainBroken

TICKET_NAME = "ticket.md"
COPY_NAME = "redlines.copy"
_HEADING = re.compile(r"^##\s*(意图|红线|现场)\s*$")
_BULLET = re.compile(r"^(?:[-*•]+|\d+[.)])\s+")


def ticket_path(root: Path) -> Path:
    return Path(root) / ".data" / TICKET_NAME


def copy_path(root: Path) -> Path:
    return Path(root) / ".data" / COPY_NAME


def require_ticket(root: Path) -> str:
    path = ticket_path(root)
    if not path.is_file():
        raise ChainBroken(f"ag_start requires .data/ticket.md; missing {path}")
    return path.read_text(encoding="utf-8")


def split_document(text: str) -> tuple[str, str]:
    """Return the intent body and the red-line body.

    The intent body is the exact `## 意图` slice, or the preamble when that
    heading is absent. Later scene writes must put this slice back unchanged.
    """
    sections: dict[str, list[str]] = {"preamble": []}
    current = "preamble"
    seen: set[str] = set()
    for line in str(text or "").splitlines(keepends=True):
        match = _HEADING.match(line.strip())
        if match:
            current = match.group(1)
            seen.add(current)
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, [])
        sections[current].append(line)
    if "意图" in seen:
        intent = "".join(sections.get("意图") or [])
    else:
        intent = "".join(sections.get("preamble") or [])
    redline = "".join(sections.get("红线") or [])
    return intent, redline


def section_lines(body: str) -> list[str]:
    lines: list[str] = []
    for raw in str(body or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = _BULLET.sub("", line).strip()
        if line and line not in lines:
            lines.append(line)
    return lines


def collect_redlines(redline_body: str, anchors: list[dict[str, Any]]) -> list[str]:
    lines = section_lines(redline_body)
    for item in anchors:
        if not isinstance(item, dict) or str(item.get("kind") or "") != "hard":
            continue
        text = str(item.get("text") or "").strip()
        if text and text not in lines:
            lines.append(text)
    return lines


def merge_anchors(
    document_anchors: list[dict[str, Any]],
    caller_anchors: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    merged = [dict(item) for item in document_anchors if isinstance(item, dict)]
    seen = {str(item.get("text") or "").strip() for item in merged}
    for item in caller_anchors or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        row = dict(item)
        row["text"] = text
        if not str(row.get("id") or "").strip():
            row["id"] = f"a{len(merged) + 1}"
        merged.append(row)
    return merged


def scene_text(task: dict[str, Any], *, process: str, product: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [
        f"task: {task.get('id') or ''}",
        f"process: {process}",
        f"product: {product}",
        f"worktree: {task.get('worktree') or ''}",
        f"branch: {task.get('branch') or ''}",
        f"updated: {stamp}",
    ]
    return "\n".join(rows) + "\n"


def seal(
    root: Path,
    *,
    intent_body: str,
    redlines: list[str],
    task: dict[str, Any],
    process: str,
    product: str,
) -> str:
    path = ticket_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    intent = intent_body
    if intent and not intent.endswith("\n"):
        intent += "\n"
    red = "".join(f"- {line}\n" for line in redlines)
    scene = scene_text(task, process=process, product=product)
    text = f"# 票\n\n## 意图\n{intent}\n## 红线\n{red}\n## 现场\n{scene}"
    path.write_text(text, encoding="utf-8")
    copy_path(root).write_text(("\n".join(redlines) + "\n") if redlines else "", encoding="utf-8")
    return text


def write_scene(root: Path, task: dict[str, Any], *, process: str, product: str) -> str | None:
    """Rewrite `## 现场` only. Missing ticket file is left absent."""
    path = ticket_path(root)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    block = "## 现场\n" + scene_text(task, process=process, product=product)
    lines = text.splitlines(keepends=True)
    cut: int | None = None
    for index, line in enumerate(lines):
        match = _HEADING.match(line.strip())
        if match and match.group(1) == "现场":
            cut = index
            break
    if cut is None:
        body = text if text.endswith("\n") else text + "\n"
        if not body.endswith("\n\n"):
            body += "\n"
        updated = body + block
    else:
        updated = "".join(lines[:cut]) + block
    path.write_text(updated, encoding="utf-8")
    return updated
