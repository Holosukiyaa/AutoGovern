"""Strategy catalog in SQLite. Probes bind to (lane, seq), e.g. ship-9.

Every handler must call enabled() before running. Core ship rows are not pluggable.
Unplug writes managed.json off[] and never touches the product tree.
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from typing import Any

from .managed import ChainBroken, ag_home, load_managed, lookup_project, project_key, save_managed

DB_PATH = Path(__file__).with_name("strategies.sqlite")

TOOLS = [
    {
        "name": "ag_plug",
        "description": "List or toggle pluggable strategies by lane-seq (lift-4). Core ship rows cannot be unplugged.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "action": {"type": "string", "enum": ["list", "on", "off"]},
                "code": {"type": "string"},
            },
            "required": ["root", "action"],
        },
    }
]


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


def parse_code(code: str) -> tuple[str, int]:
    text = str(code or "").strip()
    if "-" not in text:
        raise ChainBroken("code must look like lift-4")
    lane, _, rest = text.partition("-")
    try:
        seq = int(rest)
    except ValueError as exc:
        raise ChainBroken("code must look like lift-4") from exc
    if lane not in {"ship", "heal", "lift", "see"}:
        raise ChainBroken(f"unknown lane {lane}")
    return lane, seq


def plug_dir(root: Path, lane: str, seq: int) -> Path:
    """Only place a strategy may persist files. Unplug deletes this folder."""
    return ag_home() / "projects" / project_key(root) / "plug" / f"{lane}-{seq}"


def wipe_plug(root: Path, lane: str, seq: int) -> str:
    folder = plug_dir(root, lane, seq)
    if folder.is_dir():
        shutil.rmtree(folder)
        return str(folder)
    return ""


def gc_plug(root: Path) -> list[str]:
    """Delete plug folders whose lane-seq is no longer in the catalog."""
    folder = ag_home() / "projects" / project_key(root) / "plug"
    if not folder.is_dir():
        return []
    valid = {item["code"] for lane in ("ship", "lift", "heal", "see") for item in list_lane(lane)}
    wiped: list[str] = []
    for child in folder.iterdir():
        if child.is_dir() and child.name not in valid:
            shutil.rmtree(child)
            wiped.append(child.name)
    return wiped


def enabled(root: Path, lane: str, seq: int) -> bool:
    item = get(lane, seq)
    if not item["pluggable"]:
        return True
    off = [str(x) for x in ((lookup_project(root) or {}).get("off") or [])]
    return item["code"] not in off


def _set_off(root: Path, off: list[str]) -> None:
    item = lookup_project(root)
    if item is None:
        raise ChainBroken(f"not enrolled: {root}")
    blob = load_managed()
    key = str(item.get("key") or "")
    for row in blob["projects"]:
        if isinstance(row, dict) and str(row.get("key") or "") == key:
            row["off"] = sorted(set(off))
            break
    save_managed(blob)


def plug_list(root: Path) -> dict[str, Any]:
    off = {str(x) for x in ((lookup_project(root) or {}).get("off") or [])}
    rows = []
    for lane in ("ship", "lift", "heal", "see"):
        for item in list_lane(lane):
            on = True if not item["pluggable"] else item["code"] not in off
            rows.append(
                {
                    "code": item["code"],
                    "name": item["name"],
                    "pluggable": item["pluggable"],
                    "on": on,
                }
            )
    return {"schema": "ag.plug.v1", "root": str(root), "items": rows, "gc": gc_plug(root)}


def plug(root: Path, code: str, *, on: bool) -> dict[str, Any]:
    lane, seq = parse_code(code)
    item = get(lane, seq)
    if not item["pluggable"]:
        raise ChainBroken(f"{item['code']} is ship core; unenroll the whole loop instead")
    off = [str(x) for x in ((lookup_project(root) or {}).get("off") or [])]
    if on:
        off = [x for x in off if x != item["code"]]
    elif item["code"] not in off:
        off.append(item["code"])
        wipe_plug(root, lane, seq)
    _set_off(root, off)
    result = plug_list(root)
    result["wiped"] = f"{lane}-{seq}" if not on else ""
    return result


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(str(args.get("root") or ""))
    action = str(args.get("action") or "list")
    if name != "ag_plug":
        raise ChainBroken(f"unknown tool {name}")
    if action == "list":
        return plug_list(root)
    if action in {"on", "off"}:
        return plug(root, str(args.get("code") or ""), on=action == "on")
    raise ChainBroken("action must be list, on, or off")
