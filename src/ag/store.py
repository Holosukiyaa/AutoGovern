"""AG_HOME side files. Review history has exactly one master: the jsonl log."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .managed import ag_home, project_key, real_root

LEGACY_DB_NAME = "ag.sqlite"
# 通用名目录：可能是项目自己的数据（例如某个项目的应用数据就放在这里）。
# ag 不再往项目里写它，扫描时一律跳过；只有搬运遗留票的那一次会读它。全仓唯一的字面量。
FOREIGN_DIR_NAME = ".data"
PENDING_NAME = "pending_repairs.json"
LLM_PREFIX = {"critic_event": "cr", "switch_event": "sw", "ticket_event": "tr"}
LLM_JSONL = {"critic_event": "critic.jsonl", "switch_event": "switch.jsonl", "ticket_event": "ticket.jsonl"}


def legacy_db_path(root: Path) -> Path:
    """The retired mirror. Read-only: nothing writes it again."""
    return ag_home() / "projects" / project_key(real_root(root)) / LEGACY_DB_NAME


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
    bad = 0
    top = 0
    text = ""
    present = path.is_file()
    if present:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
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
        seq = _report_seq(row.get("report_id"), prefix)
        if seq > top:
            top = seq
    return {"path": str(path), "present": present, "rows": rows, "bad_lines": bad, "top_seq": top}


def list_llm_events(root: Path, table: str, limit: int = 20) -> list[dict[str, Any]]:
    cap = int(limit) if limit else 20
    if cap < 0:
        cap = 20
    rows = scan_llm_log(root, table)["rows"]
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


def legacy_db_residue(root: Path) -> dict[str, Any]:
    """Rows left in the retired mirror, if an old file is still on disk. Read-only."""
    path = legacy_db_path(root)
    out: dict[str, Any] = {"path": str(path), "present": path.is_file(), "tables": {}, "rows": 0, "error": ""}
    if not out["present"]:
        return out
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        out["error"] = f"{exc.__class__.__name__}: {exc}"
        return out
    try:
        names = [
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        ]
        for name in names:
            if name == "sqlite_sequence":
                continue
            count = int(conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0])
            out["tables"][name] = count
            out["rows"] += count
    except sqlite3.Error as exc:
        out["error"] = f"{exc.__class__.__name__}: {exc}"
    finally:
        conn.close()
    return out


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
    path = latest_timeline_path(root, task_id)
    empty: dict[str, Any] = {"task_id": str(task_id or ""), "steps": [], "path": str(path or "")}
    if path is None or not path.is_file():
        return empty
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(blob, dict):
        return empty
    steps = blob.get("steps")
    return {
        "task_id": str(blob.get("task_id") or path.stem),
        "steps": steps if isinstance(steps, list) else [],
        "path": str(path),
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
    path = timeline_path(root, tid)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        blob: dict[str, Any] = {"task_id": tid, "steps": []}
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    blob = raw
            except (OSError, json.JSONDecodeError):
                pass
        steps = blob.get("steps")
        if not isinstance(steps, list):
            steps = []
        step: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "phase": str(phase),
        }
        for key, value in fields.items():
            if value is None:
                continue
            step[key] = value
        steps.append(step)
        blob["task_id"] = tid
        blob["steps"] = steps
        path.write_text(json.dumps(blob, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path
    except OSError:
        return None


def append_llm_log(root: Path, table: str, row: dict[str, Any]) -> str:
    """The only writer. Append to the jsonl master and mint the next report id from it."""
    prefix = LLM_PREFIX[table]
    try:
        scan = scan_llm_log(root, table)
        seq = max(int(scan["top_seq"]), len(scan["rows"])) + 1
        report_id = f"{prefix}-{seq}"
        row["report_id"] = report_id
        path = Path(str(scan["path"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return report_id
    except OSError:
        return ""


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
