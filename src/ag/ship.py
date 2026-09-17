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
        "description": "Open a worktree. Write only there. Optional portrait is 'done looks like'.",
        "inputSchema": {
            "type": "object",
            "properties": {"root": {"type": "string"}, "portrait": {"type": "string"}},
            "required": ["root"],
        },
    },
    {
        "name": "ag_verify",
        "description": "Run enrolled tests in the worktree and pin git write-tree. product failed is not an MCP error.",
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
        return start(root, portrait=str(args.get("portrait") or ""))
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
