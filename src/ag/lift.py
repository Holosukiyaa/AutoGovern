"""抬正确率 lane. Advice only. Must not set product or refuse finish."""
from __future__ import annotations

from typing import Any

ID = "lift"
JOB = "抬正确率"
SETS_PRODUCT = False
MAY_REFUSE_FINISH = False
TOOLS = [
    {
        "name": "ag_lift",
        "description": "Run lift strategies as advice. Does not set product or refuse finish.",
        "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}}, "required": ["root"]},
    }
]


def run(root: Any) -> dict[str, Any]:
    from pathlib import Path

    from .advice import run_lane

    return run_lane("lift", Path(root))


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    from .managed import ChainBroken

    if name == "ag_lift":
        return run(args.get("root"))
    raise ChainBroken(f"lift has no tool {name}")
