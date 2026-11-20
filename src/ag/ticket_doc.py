"""Read-only ticket archive helpers; live package handling is in ticket_package."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .managed import ChainBroken, real_root
from .store import project_dir

TICKET_NAME = "ticket.md"
COPY_NAME = "redlines.copy"
TICKETS_DIR_NAME = "tickets"
_HEADING = re.compile(r"^##\s*(意图|红线|现场)\s*$")
_BULLET = re.compile(r"^(?:[-*•]+|\d+[.)])\s+")

def home_dir(root: Path) -> Path:
    """Where this project's tickets live: inside the ag home, keyed by project."""
    return project_dir(root)


def ticket_path(root: Path) -> Path:
    return home_dir(root) / "draft" / TICKET_NAME


def copy_path(root: Path) -> Path:
    return home_dir(root) / COPY_NAME


def tickets_dir(root: Path) -> Path:
    return home_dir(root) / TICKETS_DIR_NAME


def active_ticket_path(root: Path) -> Path:
    """Where the live ticket is: the ag home, nowhere else."""
    return ticket_path(root)


def archived_ticket_docs(root: Path) -> list[Path]:
    folder = tickets_dir(root)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.md") if p.is_file()) + sorted(folder.glob("*/ticket.md"))


def archived_ticket_entries(root: Path) -> list[dict[str, Any]]:
    from .history import read_records

    rows = []
    for row in read_records(root, kind="ticket"):
        payload = row["payload"]
        rows.append({"task_id": row["task_id"], "text": str(payload.get("text") or ""), "ref": f"{row['_source']}#{row['id']}"})
    for path in archived_ticket_docs(root):
        rows.append({"task_id": path.parent.name if path.name == "ticket.md" else path.stem, "text": path.read_text(encoding="utf-8"), "ref": str(path)})
    rows.sort(key=lambda row: next((line.removeprefix("updated: ") for line in row["text"].splitlines() if line.startswith("updated: ")), ""))
    unique = {}
    for row in rows:
        unique[row["task_id"]] = row
    return list(unique.values())


def previous_redlines(root: Path) -> list[str]:
    path = copy_path(root)
    if not path.is_file():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    lines: list[str] = []
    for item in raw.splitlines():
        line = item.strip()
        if line and line not in lines:
            lines.append(line)
    return lines


def dropped_redlines(previous: list[str], current: list[str]) -> list[str]:
    keep = set(current)
    return [line for line in previous if line not in keep]


def preserve_original_ticket(root: Path, task_id: str, text: str, *, raw_bytes: bytes | None = None) -> dict[str, str]:
    """Keep exact child-ticket Markdown as an immutable, content-addressed file."""
    import hashlib
    import os

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", task_id):
        raise ChainBroken("ticket-archive-invalid-task-id")
    raw = text.encode("utf-8") if raw_bytes is None else raw_bytes
    sha = hashlib.sha256(raw).hexdigest()
    folder = tickets_dir(root) / "originals"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{task_id}-{sha}.md"
    try:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_bytes() != raw:
            raise ChainBroken("ticket-archive-conflict: original ticket content changed")
    return {"task_id": task_id, "path": str(path.resolve()), "sha256": sha}


def require_ticket(root: Path) -> str:
    from .ticket_package import load_draft
    return load_draft(root)["ticket"]


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
def classify_redlines(root: Path, redlines: list[str]) -> dict[str, list[str]]:
    from .knowledge import load_standing_redlines

    standing = load_standing_redlines(root)
    standing_set = set(standing)
    explicit = list(dict.fromkeys(str(rule).strip() for rule in redlines if str(rule).strip()))
    return {
        "redlines": list(dict.fromkeys([*standing, *explicit])),
        "standing_redlines": standing,
        "ticket_redlines": [rule for rule in explicit if rule not in standing_set],
    }
