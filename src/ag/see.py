"""看见 lane. Usage log bound to strategy seq. Must not set product or refuse finish."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .catalog import list_lane
from .managed import ag_home, lookup_project, project_key, real_root

ID = "see"
JOB = "看见"
SETS_PRODUCT = False
MAY_REFUSE_FINISH = False
TOOLS = [
    {
        "name": "ag_usage",
        "description": "Per-item help/block counts for vibe-coding. Observation only, not a green.",
        "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}}, "required": ["root"]},
    },
]


def _usage_path(key: str) -> Path:
    return ag_home() / "projects" / key / "usage.jsonl"


def note(root: Path, lane: str, seq: int, kind: str, detail: str = "") -> None:
    try:
        root = real_root(root)
        key = project_key(root)
        path = _usage_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "t": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "root": str(root),
            "key": key,
            "lane": lane,
            "seq": int(seq),
            "kind": kind,
            "detail": detail,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        return


def usage(root: Path, lane: str = "ship") -> dict[str, Any]:
    root = real_root(root)
    key = project_key(root)
    path = _usage_path(key)
    catalog = list_lane(lane)
    counts: dict[int, dict[str, int]] = {int(item["seq"]): {"help": 0, "block": 0} for item in catalog}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(row.get("lane") or lane) != lane:
                continue
            try:
                seq = int(row.get("seq"))
            except (TypeError, ValueError):
                continue
            kind = str(row.get("kind") or "")
            if seq in counts and kind in {"help", "block"}:
                counts[seq][kind] += 1
    rows = []
    never = []
    for item in catalog:
        seq = int(item["seq"])
        help_n = counts[seq]["help"]
        block_n = counts[seq]["block"]
        code = str(item["code"])
        rows.append(
            {
                "lane": lane,
                "seq": seq,
                "code": code,
                "name": item["name"],
                "help": help_n,
                "block": block_n,
                "hits": help_n + block_n,
            }
        )
        if help_n + block_n == 0:
            never.append(code)
    enrolled = lookup_project(root) is not None
    return {
        "schema": "ag.usage.v1",
        "root": str(root),
        "key": key,
        "lane": lane,
        "enrolled": enrolled,
        "reminder": "hits bind to lane-seq (ship-9), not a slug id; not product green",
        "items": rows,
        "never_used": never,
    }


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    from .managed import ChainBroken

    if name == "ag_usage":
        return usage(Path(str(args.get("root") or "")))
    raise ChainBroken(f"see has no tool {name}")
