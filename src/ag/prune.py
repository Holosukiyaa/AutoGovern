"""Reclaim closed history only after durable, verified archive publication."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .history import migrate_closed
from .managed import ChainBroken, project_key, real_root
from .store import append_project_jsonl, project_dir


def _active_task_id(root: Path) -> str:
    from .loop import load_task

    return str((load_task(project_key(real_root(root))) or {}).get("id") or "")


def prune(root: Path) -> dict[str, Any]:
    root = real_root(root)
    base = project_dir(root)
    if not base.is_dir():
        raise ChainBroken(f"no project state dir: {base}")
    active_id = _active_task_id(root)
    archived = migrate_closed(root, active_id)
    removed_live = []
    freed = archived["freed_bytes"]
    append_project_jsonl(root, "cleanup-audit.jsonl", {"action": "archive-closed-history", "removed": archived["removed"], "volumes": archived["volumes"], "freed_bytes": archived["freed_bytes"]})
    return {"schema": "ag.prune.v2", "root": str(root), "active_task": active_id or None, "removed_live": removed_live, "compacted_tasks": [], "merged_tasks": [name for name in archived["removed"] if name.startswith("tasks/")], "freed_bytes": freed, "archive": archived}
