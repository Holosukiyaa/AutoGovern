"""Registry of other projects. ag does not probe itself."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .queue import ChainBroken, git_head, load_queue, queue_path, save_queue

SCHEMA = "ag.managed.v1"


def managed_path() -> Path:
    return Path.home() / ".ag" / "managed.json"


def load_managed() -> dict[str, Any]:
    path = managed_path()
    if not path.is_file():
        return {"schema": SCHEMA, "projects": []}
    blob = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(blob, dict):
        raise ChainBroken("managed file is not an object")
    projects = blob.get("projects")
    if not isinstance(projects, list):
        projects = []
    return {"schema": SCHEMA, "projects": projects}


def save_managed(blob: dict[str, Any]) -> Path:
    path = managed_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def add_project(root: Path, *, note: str = "") -> dict[str, Any]:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ChainBroken(f"not a directory: {root}")
    blob = load_managed()
    existing = {str(Path(str(item.get("root") or "")).resolve()) for item in blob["projects"] if isinstance(item, dict)}
    if str(root) in existing:
        raise ChainBroken(f"already managed: {root}")
    save_queue(root, load_queue(root))
    item = {"root": str(root), "note": str(note or "")}
    blob["projects"].append(item)
    save_managed(blob)
    return item


def project_snapshot(root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    queue = load_queue(root)
    items = []
    for item in queue.get("items") or []:
        if not isinstance(item, dict):
            continue
        last = item.get("last") if isinstance(item.get("last"), dict) else {}
        items.append(
            {
                "id": item.get("id"),
                "kind": item.get("kind"),
                "path": item.get("path"),
                "note": item.get("note"),
                "trusted": bool(last.get("trusted")),
                "skipped": bool(last.get("skipped")),
                "red_ok": last.get("red_ok"),
                "green_ok": last.get("green_ok"),
                "unverifiable": bool(last.get("unverifiable") or item.get("kind") == "unknown"),
                "pin": item.get("pin"),
            }
        )
    trusted_n = sum(1 for p in items if p.get("trusted"))
    total = len(items)
    queue_blob = load_queue(root)
    last_run = queue_blob.get("last_run") if isinstance(queue_blob.get("last_run"), dict) else {}
    head = git_head(root)
    stale = bool(last_run.get("git_head") and head and last_run.get("git_head") != head)
    return {
        "root": str(root),
        "queue": str(queue_path(root)),
        "items": items,
        "trust_rate": None if total == 0 else round(trusted_n / total, 4),
        "reminder": "trust_rate is a reminder; low rate does not stop the business",
        "last_run": last_run,
        "git_head": head,
        "stale": stale,
    }
