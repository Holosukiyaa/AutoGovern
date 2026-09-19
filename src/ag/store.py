"""Project SQLite under AG_HOME. Not in the product tree."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from .managed import ag_home, project_key, real_root

DB_NAME = "ag.sqlite"
PENDING_NAME = "pending_repairs.json"
LLM_PREFIX = {"critic_event": "cr", "switch_event": "sw"}
LLM_JSONL = {"critic_event": "critic.jsonl", "switch_event": "switch.jsonl"}
LLM_INSERT = """
INSERT INTO {table} (
    ts, outcome, reason, configured, prompt_version, store,
    exam_sha256, pack_sha256, items_json, task_id, model,
    probe_red_json, allow_same_family, thinking, timings_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def db_path(root: Path) -> Path:
    return ag_home() / "projects" / project_key(real_root(root)) / DB_NAME


def connect(root: Path) -> sqlite3.Connection:
    path = db_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS critic_event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            outcome TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            configured INTEGER NOT NULL DEFAULT 0,
            prompt_version TEXT NOT NULL DEFAULT '',
            store TEXT NOT NULL DEFAULT '',
            exam_sha256 TEXT NOT NULL DEFAULT '',
            pack_sha256 TEXT NOT NULL DEFAULT '',
            items_json TEXT NOT NULL DEFAULT '[]',
            task_id TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            probe_red_json TEXT NOT NULL DEFAULT '[]',
            allow_same_family INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS probe (
            id TEXT PRIMARY KEY,
            state TEXT NOT NULL DEFAULT 'armed',
            quiet_count INTEGER NOT NULL DEFAULT 0,
            ttl_quiet_loops INTEGER NOT NULL DEFAULT 10,
            area_json TEXT NOT NULL DEFAULT '[]',
            exam_fragment TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS heal_event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            needles_json TEXT NOT NULL DEFAULT '[]',
            diseases_json TEXT NOT NULL DEFAULT '[]',
            repair_portrait TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS switch_event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            outcome TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            configured INTEGER NOT NULL DEFAULT 0,
            prompt_version TEXT NOT NULL DEFAULT '',
            store TEXT NOT NULL DEFAULT '',
            exam_sha256 TEXT NOT NULL DEFAULT '',
            pack_sha256 TEXT NOT NULL DEFAULT '',
            items_json TEXT NOT NULL DEFAULT '[]',
            task_id TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            probe_red_json TEXT NOT NULL DEFAULT '[]',
            allow_same_family INTEGER NOT NULL DEFAULT 0,
            thinking TEXT NOT NULL DEFAULT '',
            timings_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    cols = {str(item[1]) for item in conn.execute("PRAGMA table_info(critic_event)").fetchall()}
    if "thinking" not in cols:
        conn.execute("ALTER TABLE critic_event ADD COLUMN thinking TEXT NOT NULL DEFAULT ''")
    if "timings_json" not in cols:
        conn.execute("ALTER TABLE critic_event ADD COLUMN timings_json TEXT NOT NULL DEFAULT '{}'")
    conn.commit()
    return conn


def insert_llm_event(root: Path, table: str, row: dict[str, Any]) -> int:
    if table not in LLM_PREFIX:
        raise ValueError(table)
    conn = connect(root)
    try:
        cur = conn.execute(
            LLM_INSERT.format(table=table),
            (
                str(row.get("ts") or ""),
                str(row.get("outcome") or ""),
                str(row.get("reason") or ""),
                1 if row.get("configured") else 0,
                str(row.get("prompt_version") or ""),
                str(row.get("store") or ""),
                str(row.get("exam_sha256") or ""),
                str(row.get("pack_sha256") or ""),
                json.dumps(row.get("items") or [], ensure_ascii=False),
                str(row.get("task_id") or ""),
                str(row.get("model") or ""),
                json.dumps(row.get("probe_red") or [], ensure_ascii=False),
                1 if row.get("allow_same_family") else 0,
                str(row.get("thinking") or "")[:20000],
                json.dumps(row.get("timings") or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


def insert_critic_event(root: Path, row: dict[str, Any]) -> int:
    return insert_llm_event(root, "critic_event", row)


def _row_to_event(row: sqlite3.Row, prefix: str = "cr") -> dict[str, Any]:
    items = json.loads(row["items_json"] or "[]")
    probe_red = json.loads(row["probe_red_json"] or "[]")
    prefix = str(prefix or "cr")
    out: dict[str, Any] = {
        "report_id": f"{prefix}-{row['id']}",
        "ts": row["ts"],
        "outcome": row["outcome"],
        "reason": row["reason"],
        "configured": bool(row["configured"]),
        "prompt_version": row["prompt_version"],
        "store": row["store"],
        "exam_sha256": row["exam_sha256"],
        "pack_sha256": row["pack_sha256"],
        "items": items if isinstance(items, list) else [],
    }
    if row["task_id"]:
        out["task_id"] = row["task_id"]
    if row["model"]:
        out["model"] = row["model"]
    if probe_red:
        out["probe_red"] = probe_red
    if row["allow_same_family"]:
        out["allow_same_family"] = True
    keys = set(row.keys())
    if "thinking" in keys and row["thinking"]:
        out["thinking"] = str(row["thinking"])
    if "timings_json" in keys and row["timings_json"]:
        try:
            timings = json.loads(row["timings_json"])
        except json.JSONDecodeError:
            timings = {}
        if isinstance(timings, dict) and timings:
            out["timings"] = timings
    return out


def insert_switch_event(root: Path, row: dict[str, Any]) -> int:
    return insert_llm_event(root, "switch_event", row)


def list_llm_events(root: Path, table: str, limit: int = 20) -> list[dict[str, Any]]:
    prefix = LLM_PREFIX.get(table)
    if not prefix:
        raise ValueError(table)
    conn = connect(root)
    try:
        cap = int(limit) if limit else 20
        if cap < 0:
            cap = 20
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY id ASC").fetchall()
    finally:
        conn.close()
    events = [_row_to_event(row, prefix) for row in rows]
    if cap > 0:
        return events[-cap:]
    return events


def list_switch_events(root: Path, limit: int = 20) -> list[dict[str, Any]]:
    return list_llm_events(root, "switch_event", limit=limit)


def list_critic_events(root: Path, limit: int = 20) -> list[dict[str, Any]]:
    return list_llm_events(root, "critic_event", limit=limit)


def project_dir(root: Path) -> Path:
    return ag_home() / "projects" / project_key(real_root(root))


def append_llm_log(root: Path, table: str, row: dict[str, Any]) -> str:
    prefix = LLM_PREFIX[table]
    name = LLM_JSONL[table]
    try:
        path = project_dir(root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            row_id = insert_llm_event(root, table, row)
            report_id = f"{prefix}-{row_id}" if row_id else ""
        except Exception:
            blob = str(row.get("ts") or "") + str(row.get("outcome") or "") + str(row.get("exam_sha256") or "")
            report_id = prefix + "-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
        if report_id:
            row["report_id"] = report_id
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return report_id
    except OSError:
        return ""


def upsert_probe(root: Path, row: dict[str, Any]) -> None:
    conn = connect(root)
    try:
        conn.execute(
            """
            INSERT INTO probe (id, state, quiet_count, ttl_quiet_loops, area_json, exam_fragment)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                state=excluded.state,
                quiet_count=excluded.quiet_count,
                ttl_quiet_loops=excluded.ttl_quiet_loops,
                area_json=excluded.area_json,
                exam_fragment=excluded.exam_fragment
            """,
            (
                str(row.get("id") or ""),
                str(row.get("state") or "armed"),
                int(row.get("quiet_count") or 0),
                int(row.get("ttl_quiet_loops") or 10),
                json.dumps(row.get("area") or [], ensure_ascii=False),
                str(row.get("exam_fragment") or ""),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def list_probe_rows(root: Path) -> list[dict[str, Any]]:
    conn = connect(root)
    try:
        rows = conn.execute(
            "SELECT id, state, quiet_count, ttl_quiet_loops, area_json, exam_fragment FROM probe ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        area = json.loads(row["area_json"] or "[]")
        out.append(
            {
                "id": row["id"],
                "state": row["state"],
                "quiet_count": int(row["quiet_count"]),
                "ttl_quiet_loops": int(row["ttl_quiet_loops"]),
                "area": area if isinstance(area, list) else [],
                "exam_fragment": row["exam_fragment"],
            }
        )
    return out


def insert_heal_event(root: Path, row: dict[str, Any]) -> str:
    conn = connect(root)
    try:
        cur = conn.execute(
            """
            INSERT INTO heal_event (ts, needles_json, diseases_json, repair_portrait)
            VALUES (?, ?, ?, ?)
            """,
            (
                str(row.get("ts") or ""),
                json.dumps(row.get("needles") or [], ensure_ascii=False),
                json.dumps(row.get("diseases") or [], ensure_ascii=False),
                str(row.get("repair_portrait") or ""),
            ),
        )
        conn.commit()
        return f"hp-{int(cur.lastrowid or 0)}"
    finally:
        conn.close()


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


def event_count(root: Path) -> int:
    conn = connect(root)
    try:
        value = conn.execute("SELECT COUNT(*) FROM critic_event").fetchone()[0]
    finally:
        conn.close()
    return int(value)
