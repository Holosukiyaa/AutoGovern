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


def _merge_compacted_tasks(tasks_dir: Path, root: Path, active_id: str, freed: list[int], exclude: set[str] | None = None) -> list[str]:
    """Fold compacted one-line task indexes into tasks/index.jsonl, then drop the loose files.

    Only files whose JSON body has compacted:true are merged (they are prune's own residue).
    Unfinished timelines (with steps), the active task, task.json and index.jsonl stay put.
    Each task_id is appended once (dedup by id already present in index). Every delete is audited.
    """
    index_path = tasks_dir / "index.jsonl"
    existing_ids: set[str] = set()
    if index_path.is_file():
        try:
            for ln in index_path.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    row = json.loads(ln)
                except ValueError:
                    continue
                tid = str(row.get("task_id") or "").strip()
                if tid:
                    existing_ids.add(tid)
        except OSError:
            pass
    merged: list[str] = []
    new_lines: list[str] = []
    for path in sorted(tasks_dir.glob("*.json")):
        if not path.is_file():
            continue
        if path.name == "task.json" or (active_id and path.stem == active_id):
            continue
        if exclude and path.name in exclude:
            continue  # just compacted this run; keep its index one more cycle for traceability
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not (isinstance(blob, dict) and blob.get("compacted") is True):
            continue  # leave uncompressed timelines (with steps) untouched
        tid = str(blob.get("task_id") or path.stem).strip() or path.stem
        if tid and tid not in existing_ids:
            row = {
                "task_id": tid,
                "process": str(blob.get("process") or ""),
                "product": str(blob.get("product") or ""),
                "step_count": int(blob.get("step_count") or 0),
            }
            new_lines.append(json.dumps(row, ensure_ascii=False))
            existing_ids.add(tid)
        if _drop(path, root, "merge-compacted-task", freed):
            merged.append(path.name)
    if new_lines:
        try:
            with index_path.open("a", encoding="utf-8") as fh:
                for ln in new_lines:
                    fh.write(ln + "\n")
        except OSError:
            pass
    return merged


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

    # 3) fold already-compacted one-line residues into tasks/index.jsonl, then drop them.
    merged: list[str] = []
    if tasks_dir.is_dir():
        merged = _merge_compacted_tasks(tasks_dir, root, active_id, freed, exclude=set(compacted))

    return {
        "schema": "ag.prune.v1",
        "root": str(root),
        "active_task": active_id or None,
        "removed_live": removed,
        "compacted_tasks": compacted,
        "merged_tasks": merged,
        "freed_bytes": sum(freed),
    }
