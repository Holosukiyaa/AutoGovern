"""治病 lane. Findings only. Must not set product or refuse finish."""
from __future__ import annotations

from typing import Any

ID = "heal"
JOB = "治病"
SETS_PRODUCT = False
MAY_REFUSE_FINISH = False
TOOLS: list[dict[str, Any]] = []


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    from .managed import ChainBroken

    raise ChainBroken(f"heal has no tool {name}")
