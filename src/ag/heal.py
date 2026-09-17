"""治病 lane. 叠门对症. Findings only. Must not set product or refuse finish."""
from __future__ import annotations

from typing import Any

ID = "heal"
JOB = "治病"
SETS_PRODUCT = False
MAY_REFUSE_FINISH = False
TOOLS = [
    {
        "name": "ag_heal",
        "description": "Stacked-door prescription (typical: CF CSS 00-103 overlay). Not on the delivery path; run only after doors are found. Does not set product or refuse finish.",
        "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}}, "required": ["root"]},
    }
]


def run(root: Any) -> dict[str, Any]:
    from pathlib import Path

    from .advice import run_lane

    return run_lane("heal", Path(root))


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    from .managed import ChainBroken

    if name == "ag_heal":
        return run(args.get("root"))
    raise ChainBroken(f"heal has no tool {name}")
