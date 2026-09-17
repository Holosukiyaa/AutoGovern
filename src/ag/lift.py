"""抬正确率 lane. Advice only. Must not set product or refuse finish."""
from __future__ import annotations

from typing import Any

ID = "lift"
JOB = "抬正确率"
SETS_PRODUCT = False
MAY_REFUSE_FINISH = False
TOOLS: list[dict[str, Any]] = []


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    from .managed import ChainBroken

    raise ChainBroken(f"lift has no tool {name}")
