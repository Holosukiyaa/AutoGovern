"""Bounded-storage pruning for a project's AG_HOME state (ship lane helper).

Keep conclusions, cut process noise. Old -live.jsonl copies and finished-task
step timelines are pure residue after a ticket closes; prune collapses them to
one index line each. Foundations never move: tickets/, knowledge/, *-last.json,
the probe store, and the ACTIVE task's files stay byte-identical.

Pure stdlib. Every deletion/compaction writes one audit line — never silent.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .managed import ChainBroken, project_key, real_root
from .store import append_project_jsonl, project_dir

def _audit_fail(root: Path, action: str, file: str) -> None:
    """Audit write failed: surface it instead of swallowing. Deletion already happened."""
    import sys

    sys.stderr.write(f"ag: prune audit write failed for {action} on {file}; action happened but was not logged\n")

_LIVE_SUFFIX = "-live.jsonl"
# Foundations that must never be touched by prune.
_PROTECTED_DIRS = {"tickets", "knowledge", "probes", "adapters", "checks", "plug"}
_PROTECTED_FILES = {"ticket.md", "redlines.copy", "config.json", "critic.json", "project.txt", "task.json", "probes.json", "probe-audit.jsonl"}


def _audit(root: Path, action: str, file: str, freed: int) -> None:
    try:
        append_project_jsonl(root, "cleanup-audit.jsonl", {
            "action": action,
            "file": file,
            "freed_bytes": int(freed),
        })
    except Exception:
        _audit_fail(root, action, file)


def _drop(path: Path, root: Path, action: str, freed: list[int]) -> bool:
    try:
        size = int(path.stat().st_size)
        path.unlink()
    except OSError:
        return False
    freed.append(size)
    _audit(root, action, path.name, size)
    return True


def _active_task_id(root: Path) -> str:
    try:
        from .loop import load_task

        task = load_task(project_key(real_root(root)))
        return str((task or {}).get("id") or "")
    except Exception:
        return ""


def _is_last_conclusion(name: str) -> bool:
    return name.endswith("-last.json")


def _compact_task_file(path: Path, root: Path, freed: list[int]) -> bool:
    """Collapse a finished task's step timeline to one index line. Returns True if compacted."""
    try:
        before = int(path.stat().st_size)
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    steps = blob.get("steps") if isinstance(blob, dict) else None
    if not isinstance(steps, list) or not steps:
        return False
    last = steps[-1] if isinstance(steps[-1], dict) else {}
    index = {
        "task_id": str(blob.get("task_id") or path.stem),
        "process": str(last.get("step") or last.get("phase") or ""),
        "product": str(last.get("product") or ""),
        "step_count": len(steps),
        "compacted": True,
    }
    try:
        path.write_text(json.dumps(index, ensure_ascii=False) + "\n", encoding="utf-8")
        after = int(path.stat().st_size)
    except OSError:
        return False
    freed.append(max(0, before - after))
    _audit(root, "compact-task-timeline", path.name, max(0, before - after))
    return True


def prune(root: Path) -> dict[str, Any]:
    """Prune old process residue in a project's AG_HOME dir. Foundations stay untouched.

    Deletes stale -live.jsonl copies under notes/ and reviews/, and compacts finished-task
    timelines under tasks/. Never touches the active task, conclusions, tickets, knowledge,
    or the probe store. Every action is audited.
    """
    root = real_root(root)
    base = project_dir(root)
    if not base.is_dir():
        raise ChainBroken(f"no project state dir: {base}")
    active_id = _active_task_id(root)
    freed: list[int] = []
    removed: list[str] = []
    compacted: list[str] = []

    # 1) stale -live.jsonl process logs anywhere under the project dir.
    for path in sorted(base.rglob(f"*{_LIVE_SUFFIX}")):
        if not path.is_file():
            continue
        # never touch a live log for the currently-active seat run (file is being appended).
        # A live log belongs to an in-flight seat; if a seat is mid-run we must not cut it.
        # We only prune residue, so skip the top-level live log while its task is active.
        rel_parts = path.relative_to(base).parts
        # foundations are untouchable at ANY depth: if any path segment is a protected
        # dir name (tickets/, knowledge/, probes/, ...) the copy there stays byte-identical.
        if set(rel_parts) & _PROTECTED_DIRS:
            continue
        if path.name in _PROTECTED_FILES:
            continue
        if _is_last_conclusion(path.name):
            continue
        rel = path.relative_to(base).as_posix()
        top_level = path.parent == base
        if top_level and active_id:
            continue
        if _drop(path, root, "drop-stale-live", freed):
            removed.append(rel)

    # 2) compact finished-task timelines; active task's file is off-limits.
    tasks_dir = base / "tasks"
    if tasks_dir.is_dir():
        for path in sorted(tasks_dir.glob("*.json")):
            if not path.is_file():
                continue
            # off-limits: the live task pointer file and the active ticket's own archive
            if path.name == "task.json" or (active_id and path.stem == active_id):
                continue
            if _compact_task_file(path, root, freed):
                compacted.append(path.name)

    return {
        "schema": "ag.prune.v1",
        "root": str(root),
        "active_task": active_id or None,
        "removed_live": removed,
        "compacted_tasks": compacted,
        "freed_bytes": sum(freed),
    }
