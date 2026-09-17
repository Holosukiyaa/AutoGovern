"""Strategy catalog in SQLite. Probes bind to (lane, seq), e.g. ship-9."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).with_name("strategies.sqlite")


def connect() -> sqlite3.Connection:
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"strategy catalog missing: {DB_PATH}")
    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _row(raw: sqlite3.Row) -> dict[str, Any]:
    return {
        "lane": str(raw["lane"]),
        "seq": int(raw["seq"]),
        "code": f"{raw['lane']}-{raw['seq']}",
        "name": str(raw["name"]),
        "story": str(raw["story"]),
        "how": str(raw["how"]),
        "solves": str(raw["solves"]),
        "not": str(raw["not_that"] or ""),
        "pluggable": bool(raw["pluggable"]),
        "live": bool(raw["live"]),
        "in_product_tree": bool(raw["in_product_tree"]),
        "probe": "usage",
    }


def list_lane(lane: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM strategy WHERE lane = ? ORDER BY seq",
            (lane,),
        ).fetchall()
    return [_row(item) for item in rows]


def get(lane: str, seq: int) -> dict[str, Any]:
    with connect() as conn:
        raw = conn.execute(
            "SELECT * FROM strategy WHERE lane = ? AND seq = ?",
            (lane, seq),
        ).fetchone()
    if raw is None:
        raise KeyError(f"no strategy {lane}-{seq}")
    return _row(raw)
