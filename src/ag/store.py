"""AG_HOME side files. Review history has exactly one master: the jsonl log."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .managed import ChainBroken, ag_home, project_key, real_root

# 通用名目录：可能是项目自己的数据（例如某个项目的应用数据就放在这里）。
# ag 不再往项目里写它，扫描时一律跳过。全仓唯一的字面量。
FOREIGN_DIR_NAME = ".data"
PENDING_NAME = "pending_repairs.json"
LLM_PREFIX = {"critic_event": "cr", "switch_event": "sw", "ticket_event": "tr"}
LLM_JSONL = {"critic_event": "critic.jsonl", "switch_event": "switch.jsonl", "ticket_event": "ticket.jsonl"}


def under_foreign(rel: Any) -> bool:
    """True for a project-relative path that sits inside the foreign directory."""
    text = str(rel or "").replace("\\", "/").strip("/")
    return text == FOREIGN_DIR_NAME or text.startswith(FOREIGN_DIR_NAME + "/")


def foreign_dir(root: Path) -> Path:
    """The generic per-project directory ag keeps its hands off of."""
    return Path(real_root(root)) / FOREIGN_DIR_NAME


def project_dir(root: Path) -> Path:
    return ag_home() / "projects" / project_key(real_root(root))


def append_project_jsonl(root: Path, name: str, row: dict[str, Any]) -> str:
    path = project_dir(root) / str(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return str(path)


def llm_log_path(root: Path, table: str) -> Path:
    name = LLM_JSONL.get(table)
    if not name:
        raise ValueError(table)
    return project_dir(root) / name


def _report_seq(report_id: Any, prefix: str) -> int:
    text = str(report_id or "").strip()
    head = f"{prefix}-"
    if not text.startswith(head):
        return 0
    tail = text[len(head):].strip()
    return int(tail) if tail.isdigit() else 0


def scan_llm_log(root: Path, table: str) -> dict[str, Any]:
    """Read the one master log. Bad lines are skipped and counted, never silent."""
    prefix = LLM_PREFIX[table]
    path = llm_log_path(root, table)
    rows: list[dict[str, Any]] = []
    references: dict[str, str] = {}
    diagnostics = []
    bad = 0
    top = 0
    text = ""
    present = path.is_file()
    if present:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ChainBroken(f"history-source-error: {path}: {exc}") from exc
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            bad += 1
            continue
        if not isinstance(row, dict):
            bad += 1
            continue
        rows.append(row)
        references[str(row.get("report_id") or "")] = f"{path}#{row.get('report_id') or ''}"
        seq = _report_seq(row.get("report_id"), prefix)
        if seq > top:
            top = seq
    from .history import read_records

    for archived in read_records(root, kind=table):
        row = archived["payload"]
        if row.get("task_id") != archived["task_id"]:
            diagnostics.append({"kind": "wrong-task", "source": archived["_source"], "expected_task_id": archived["task_id"], "task_id": row.get("task_id"), "report_id": row.get("report_id")})
            continue
        rows.append(row)
        references[str(row.get("report_id") or "")] = f"{archived['_source']}#{archived['id']}"
    unique = {}
    for number, row in enumerate(rows):
        identity = str(row.get("report_id") or f"unidentified-{number}")
        if identity in unique and unique[identity] != row:
            raise ChainBroken(f"history-identity-conflict: {table}/{identity}")
        unique[identity] = row
        top = max(top, _report_seq(row.get("report_id"), prefix))
    rows = sorted(unique.values(), key=lambda row: (_report_seq(row.get("report_id"), prefix), str(row.get("ts") or "")))
    return {"path": str(path), "present": present or bool(rows), "rows": rows, "bad_lines": bad, "top_seq": top, "refs": references, "diagnostics": diagnostics}


def list_llm_events(root: Path, table: str, limit: int = 20, *, task_id: str = "", report_id: str = "", candidate: str = "") -> list[dict[str, Any]]:
    cap = int(limit)
    if cap < 0:
        cap = 20
    rows = scan_llm_log(root, table)["rows"]
    rows = [row for row in rows if (not task_id or row.get("task_id") == task_id) and (not report_id or row.get("report_id") == report_id) and (not candidate or row.get("candidate") == candidate)]
    return rows[-cap:] if cap > 0 else rows


def list_switch_events(root: Path, limit: int = 20) -> list[dict[str, Any]]:
    return list_llm_events(root, "switch_event", limit=limit)


def list_critic_events(root: Path, limit: int = 20) -> list[dict[str, Any]]:
    return list_llm_events(root, "critic_event", limit=limit)


def list_ticket_events(root: Path, limit: int = 20) -> list[dict[str, Any]]:
    return list_llm_events(root, "ticket_event", limit=limit)


def last_llm_event(root: Path, table: str) -> dict[str, Any] | None:
    rows = scan_llm_log(root, table)["rows"]
    return dict(rows[-1]) if rows else None


def timeline_path(root: Path, task_id: str) -> Path:
    return project_dir(root) / "tasks" / f"{task_id}.json"


def latest_timeline_path(root: Path, task_id: str = "") -> Path | None:
    if str(task_id or "").strip():
        path = timeline_path(root, str(task_id).strip())
        return path if path.is_file() else None
    folder = project_dir(root) / "tasks"
    if not folder.is_dir():
        return None
    files = [path for path in folder.glob("*.json") if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def load_task_timeline(root: Path, task_id: str = "") -> dict[str, Any]:
    from .history import read_records

    archived = read_records(root, task_id=task_id)
    if not task_id:
        identified = [row for row in archived if row["kind"] in {"timeline", "task-step"}]
        if identified:
            task_id = identified[-1]["task_id"]
            archived = [row for row in archived if row["task_id"] == task_id]
    path = latest_timeline_path(root, task_id)
    blob: dict[str, Any] = {}
    diagnostics = []
    for row in archived:
        if row["kind"] == "timeline":
            if row["payload"].get("task_id") != task_id:
                diagnostics.append({"kind": "wrong-task", "source": row["_source"], "expected_task_id": task_id, "task_id": row["payload"].get("task_id")})
            else:
                blob = dict(row["payload"])
    if path is not None and path.is_file():
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ChainBroken(f"history-source-error: {path}: {exc}") from exc
        if not isinstance(blob, dict):
            raise ChainBroken(f"history-source-error: expected timeline object: {path}")
    if blob.get("task_id") and blob["task_id"] != task_id:
        diagnostics.append({"kind": "wrong-task", "source": str(path), "expected_task_id": task_id, "task_id": blob["task_id"]})
        blob = {}
    steps = blob.get("steps") or []
    if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
        raise ChainBroken(f"history-source-error: invalid timeline steps: {path}")
    steps = list(steps)
    for row in archived:
        if row["kind"] == "task-step" and row["payload"] not in steps:
            steps.append(row["payload"])
    valid_steps = []
    for step in steps:
        if step.get("task_id", task_id) != task_id:
            diagnostics.append({"kind": "wrong-task", "source": str(path or project_dir(root) / "history"), "expected_task_id": task_id, "task_id": step.get("task_id")})
        else:
            valid_steps.append(step)
    steps = valid_steps
    steps.sort(key=lambda row: str(row.get("ts") or ""))
    return {
        **blob,
        "task_id": str(task_id or blob.get("task_id") or ""),
        "steps": steps,
        "path": str(path or project_dir(root) / "history"),
        "found": bool(blob or steps),
        "diagnostics": diagnostics,
    }


def ensure_start_step(root: Path, task_id: str, portrait: Any, worktree: Any) -> None:
    blob = load_task_timeline(root, task_id)
    if any(isinstance(row, dict) and row.get("phase") == "start" for row in blob.get("steps") or []):
        return
    line = (str(portrait or "").strip().splitlines() or [""])[0][:80]
    append_task_step(root, task_id, "start", portrait_line=line, worktree=str(worktree or ""))


def append_task_step(root: Path, task_id: str, phase: str, **fields: Any) -> Path | None:
    tid = str(task_id or "").strip()
    if not tid:
        return None
    from .history import append_fact

    step = {"ts": datetime.now(timezone.utc).isoformat(), "phase": str(phase), "task_id": tid}
    step.update({key: value for key, value in fields.items() if value is not None})
    reference = append_fact(root, "task-step", tid, step)
    return Path(reference.split("#", 1)[0])


def append_llm_log(root: Path, table: str, row: dict[str, Any]) -> str:
    """The only writer. Append to the jsonl master and mint the next report id from it."""
    prefix = LLM_PREFIX[table]
    from .history import append_fact

    scan = scan_llm_log(root, table)
    if scan["bad_lines"]:
        raise ChainBroken(f"history-source-error: malformed review events: {scan['path']}")
    append_fact(root, table, str(row.get("task_id") or ""), row, number_prefix=prefix, floor=max(int(scan["top_seq"]), len(scan["rows"])))
    return str(row["report_id"])


def pending_path(root: Path) -> Path:
    return ag_home() / "projects" / project_key(real_root(root)) / PENDING_NAME


def load_pending(root: Path) -> list[dict[str, Any]]:
    path = pending_path(root)
    if not path.is_file():
        return []
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(blob, list):
        return []
    return [item for item in blob if isinstance(item, dict)]


def save_pending(root: Path, items: list[dict[str, Any]]) -> None:
    path = pending_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def enqueue_repair(root: Path, item: dict[str, Any]) -> None:
    rows = load_pending(root)
    rows.append(item)
    save_pending(root, rows)


def pop_pending(root: Path) -> dict[str, Any] | None:
    rows = load_pending(root)
    if not rows:
        return None
    head = rows.pop(0)
    save_pending(root, rows)
    return head


def pending_summary(root: Path) -> dict[str, Any]:
    rows = load_pending(root)
    out: dict[str, Any] = {"count": len(rows)}
    if not rows:
        return out
    head = rows[0]
    line = str(head.get("repair_portrait") or "").splitlines()
    first = (line[0] if line else "")[:80]
    out["head"] = {
        "heal_report_id": str(head.get("heal_report_id") or ""),
        "portrait_line": first,
    }
    return out
