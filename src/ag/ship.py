"""交货 lane. The only lane that may set product or refuse finish."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .loop import abandon, confirm_map, enroll, finish, start, status, unenroll, verify

ID = "ship"
JOB = "交货"
SETS_PRODUCT = True
MAY_REFUSE_FINISH = True
TOOLS = [
    {
        "name": "ag_status",
        "description": "Read-only hook, canonical dirty state, and task-bound delivery facts. Diagnostics are explicit via ag_see.",
        "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}}, "required": ["root"]},
    },
    {
        "name": "ag_enroll",
        "description": "Register a git checkout, install the canonical-commit hook, optional test argv.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "test_argv": {"type": "array", "items": {"type": "string"}},
                "note": {"type": "string"},
            },
            "required": ["root"],
        },
    },
    {
        "name": "ag_start",
        "description": "Open a worktree. Write only there. The portrait or fixed lines lock the done-state on the map. Attention anchors are the unsettled route. Later status calls do not rewrite the locked lines.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "portrait": {"type": "string"},
                "anchors": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "text": {"type": "string"},
                            "kind": {
                                "type": "string",
                                "enum": ["soft", "hard", "discoverable", "blocking", "defaulted", "avoid", "obsolete"],
                            },
                            "source": {"type": "string"},
                        },
                        "required": ["text"],
                    },
                },
                "fixed": {"type": "array", "items": {"type": "string"}},
                "guards": {"type": "array", "items": {"type": "string"}},
                "defaults": {"type": "array", "items": {"type": "string"}},
                "continuation_of": {"type": "string"},
                "contribution": {"type": "string"},
            },
            "required": ["root"],
        },
    },
    {
        "name": "ag_confirm_map",
        "description": (
            "Human-only confirmation. The user must execute confirm-map themselves; AI must never call it. "
            "Checks current review and intent identity, then returns ready only after actual thaw."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "by": {"type": "string"},
            },
            "required": ["root"],
        },
    },
    {
        "name": "ag_verify",
        "description": "Run enrolled tests (if any), probes, critic, then switch; pin git write-tree. product failed is not an MCP error.",
        "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}}, "required": ["root"]},
    },
    {
        "name": "ag_finish",
        "description": "ff-only into canonical if digest matches, hook is on, canonical is clean.",
        "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}}, "required": ["root"]},
    },
    {
        "name": "ag_abandon",
        "description": "Drop the open worktree without merging.",
        "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}}, "required": ["root"]},
    },
    {
        "name": "ag_unenroll",
        "description": "Remove the hook and restore the previous hooksPath. Abandon any open task first.",
        "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}}, "required": ["root"]},
    },
]

TOOLS.extend([
    {"name": "ag_delivery", "description": "Read-only task facts for active or archived task_id; no installation, diagnosis, migration or authorization.", "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}, "task_id": {"type": "string"}}, "required": ["root"]}},
    {"name": "ag_route", "description": "Record a route adjustment with its reason. Commitment or hard-boundary changes wait for a user decision; this never grants approval.", "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}, "reason": {"type": "string"}, "requires_decision": {"type": "boolean"}}, "required": ["root", "reason"]}},
])


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(str(args.get("root") or "")).expanduser()
    if name == "ag_status":
        return status(root)
    if name == "ag_delivery":
        from .delivery import build_delivery_snapshot

        return build_delivery_snapshot(root, str(args.get("task_id") or ""))
    if name == "ag_route":
        from .delivery import record_route

        return record_route(root, str(args.get("reason") or ""), requires_decision=bool(args.get("requires_decision")))
    if name == "ag_enroll":
        raw = args.get("test_argv")
        test_argv = [str(x) for x in raw] if isinstance(raw, list) else None
        return enroll(root, test_argv=test_argv, note=str(args.get("note") or ""))
    if name == "ag_start":
        raw = args.get("anchors")
        anchors = [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else None
        raw_fixed = args.get("fixed")
        fixed = [str(item) for item in raw_fixed] if isinstance(raw_fixed, list) else None
        raw_guards = args.get("guards")
        guards = [str(item) for item in raw_guards] if isinstance(raw_guards, list) else None
        raw_defaults = args.get("defaults")
        defaults = [str(item) for item in raw_defaults] if isinstance(raw_defaults, list) else None
        return start(
            root,
            portrait=str(args.get("portrait") or ""),
            anchors=anchors,
            guards=guards,
            defaults=defaults,
            fixed=fixed,
            continuation_of=str(args.get("continuation_of") or ""),
            contribution=str(args.get("contribution") or ""),
        )
    if name == "ag_confirm_map":
        return confirm_map(root, by=str(args.get("by") or ""))
    if name == "ag_verify":
        return verify(root)
    if name == "ag_finish":
        return finish(root)
    if name == "ag_abandon":
        return abandon(root)
    if name == "ag_unenroll":
        return unenroll(root)
    from .managed import ChainBroken

    raise ChainBroken(f"unknown tool {name}")
