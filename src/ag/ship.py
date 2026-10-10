"""交货 lane. The only lane that may set product or refuse finish."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .loop import abandon, enroll, finish, start, status, unenroll, verify

ID = "ship"
JOB = "交货"
SETS_PRODUCT = True
MAY_REFUSE_FINISH = True
TOOLS = [
    {
        "name": "ag_status",
        "description": "Hook, dirty, open task, process vs product. Root must be enrolled.",
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
                "skip_pending": {"type": "boolean"},
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


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(str(args.get("root") or "")).expanduser()
    if name == "ag_status":
        return status(root)
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
            skip_pending=bool(args.get("skip_pending")),
        )
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
