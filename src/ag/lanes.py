"""Four lanes. Only ship may set product or refuse finish.

A strategy must carry a probe and be unpluggable without touching the product tree.
Ship core (worktree/hook/digest/tests/ff-only) is the loop, not a plugin.
"""
from __future__ import annotations

from typing import Any

from . import heal, lift, see, ship

# job: 交货 / 治病 / 抬正确率 / 看见
LANES = (
    ship,
    heal,
    lift,
    see,
)


def tools() -> list[dict[str, Any]]:
    assembled: list[dict[str, Any]] = []
    names: set[str] = set()
    for lane in LANES:
        if not lane.SETS_PRODUCT and lane.MAY_REFUSE_FINISH:
            raise RuntimeError(f"{lane.ID} cannot refuse finish without owning product")
        for item in lane.TOOLS:
            name = str(item["name"])
            if name in names:
                raise RuntimeError(f"duplicate tool {name}")
            names.add(name)
            assembled.append(item)
    return assembled


def strategy_fields(item: dict[str, Any], *, default_pluggable: bool) -> dict[str, Any]:
    in_tree = bool(item.get("in_product_tree", False))
    if in_tree:
        raise RuntimeError(f"{item.get('id')} plants in the product tree; unplug would hurt")
    return {
        "pluggable": bool(item.get("pluggable", default_pluggable)),
        "probe": str(item.get("probe") or "usage"),
        "in_product_tree": False,
    }


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    for lane in LANES:
        if any(str(item["name"]) == name for item in lane.TOOLS):
            return lane.call(name, args)
    from .managed import ChainBroken

    raise ChainBroken(f"unknown tool {name}")
