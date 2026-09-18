"""Project SQLite under AG_HOME. Not in the product tree."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .managed import ag_home, project_key, real_root

DB_NAME = "ag.sqlite"


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
    conn.commit()
    return conn


def insert_critic_event(root: Path, row: dict[str, Any]) -> int:
    conn = connect(root)
    try:
        cur = conn.execute(
            """
            INSERT INTO critic_event (
                ts, outcome, reason, configured, prompt_version, store,
                exam_sha256, pack_sha256, items_json, task_id, model,
                probe_red_json, allow_same_family
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
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
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


def _row_to_event(row: sqlite3.Row) -> dict[str, Any]:
    items = json.loads(row["items_json"] or "[]")
    probe_red = json.loads(row["probe_red_json"] or "[]")
    out: dict[str, Any] = {
        "report_id": f"cr-{row['id']}",
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
    return out


def list_critic_events(root: Path, limit: int = 20) -> list[dict[str, Any]]:
    conn = connect(root)
    try:
        cap = int(limit) if limit else 20
        if cap < 0:
            cap = 20
        rows = conn.execute(
            "SELECT * FROM critic_event ORDER BY id ASC"
        ).fetchall()
    finally:
        conn.close()
    events = [_row_to_event(row) for row in rows]
    if cap > 0:
        return events[-cap:]
    return events


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


def event_count(root: Path) -> int:
    conn = connect(root)
    try:
        value = conn.execute("SELECT COUNT(*) FROM critic_event").fetchone()[0]
    finally:
        conn.close()
    return int(value)
