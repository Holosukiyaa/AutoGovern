"""stdio MCP: the queue is the only product surface."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .managed import add_project, load_managed, project_snapshot
from .queue import ChainBroken, add_exists, add_hash, add_item, add_unknown, load_queue, run_queue

PROTOCOL = "2024-11-05"
TOOLS = [
    {
        "name": "ag_manage_list",
        "description": "List other projects ag manages. ag does not probe itself.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "ag_manage_add",
        "description": "Register another project root. Creates <root>/.ag/queue.json if needed.",
        "inputSchema": {
            "type": "object",
            "properties": {"root": {"type": "string"}, "note": {"type": "string"}},
            "required": ["root"],
        },
    },
    {
        "name": "ag_queue_list",
        "description": "List probe queue items for a project root. Physical store: <root>/.ag/queue.json.",
        "inputSchema": {
            "type": "object",
            "properties": {"root": {"type": "string", "description": "Project directory"}},
            "required": ["root"],
        },
    },
    {
        "name": "ag_queue_add",
        "description": "Add a probe. red_* must fail first (counterexample); argv/expect_exit is the green chain.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "argv": {"type": "array", "items": {"type": "string"}},
                "expect_exit": {"type": "integer", "default": 0},
                "red_argv": {"type": "array", "items": {"type": "string"}},
                "red_expect_exit": {"type": "integer"},
                "note": {"type": "string"},
            },
            "required": ["root", "argv", "red_argv", "red_expect_exit"],
        },
    },
    {
        "name": "ag_queue_add_exists",
        "description": "Add a high-trust exists fence. Same predicate: ABSENT path must miss (red), given path must exist (green).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "path": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["root", "path"],
        },
    },
    {
        "name": "ag_queue_add_hash",
        "description": "Pin a file's sha256. Same predicate: missing path must not match pin (red); file bytes must match pin (green).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "path": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["root", "path"],
        },
    },
    {
        "name": "ag_queue_add_unknown",
        "description": "Declare a scope that cannot be verified. Lowers trust_rate. Does not stop the business.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "note": {"type": "string"},
                "scope": {"type": "string"},
            },
            "required": ["root", "note"],
        },
    },
    {
        "name": "ag_queue_run",
        "description": "Run every probe: red chain then green chain. Reports exit codes. Untrusted if red does not fail as expected.",
        "inputSchema": {
            "type": "object",
            "properties": {"root": {"type": "string"}},
            "required": ["root"],
        },
    },
]


def _ok(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": message}}


def _handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = str(msg.get("method") or "")
    req_id = msg.get("id")
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    if method == "initialize":
        return _ok(
            req_id,
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ag", "version": __version__},
                "instructions": (
                    "ag is a probe queue. AI output is untrusted. "
                    "Each probe must fail its red chain then pass its green chain. "
                    "High-trust fences run first. If a fence cannot bar its field, later items are skipped, never green."
            ),
                ),
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return _ok(req_id, {})
    if method == "tools/list":
        return _ok(req_id, {"tools": TOOLS})
    if method == "tools/call":
        name = str(params.get("name") or "")
        args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        try:
            text = json.dumps(_call(name, args), ensure_ascii=False, indent=2)
        except (ChainBroken, OSError, TypeError, ValueError) as exc:
            return _ok(
                req_id,
                {"content": [{"type": "text", "text": str(exc)}], "isError": True},
            )
        return _ok(req_id, {"content": [{"type": "text", "text": text}]})
    if req_id is None:
        return None
    return _err(req_id, f"unknown method {method}")


def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "ag_manage_list":
        return load_managed()
    root = Path(str(args.get("root") or "")).expanduser()
    if name == "ag_manage_add":
        item = add_project(root, note=str(args.get("note") or ""))
        return {"added": item, "managed": load_managed()}
    if name == "ag_queue_list":
        return project_snapshot(root)
    if name == "ag_queue_add":
        argv = [str(x) for x in (args.get("argv") or [])]
        red_argv = [str(x) for x in (args.get("red_argv") or [])]
        item = add_item(
            root,
            argv=argv,
            expect_exit=int(args.get("expect_exit") or 0),
            red_argv=red_argv,
            red_expect_exit=int(args["red_expect_exit"]),
            note=str(args.get("note") or ""),
        )
        return {"added": item, "queue": load_queue(root)}
    if name == "ag_queue_add_exists":
        item = add_exists(root, str(args.get("path") or ""), note=str(args.get("note") or ""))
        return {"added": item, "queue": load_queue(root)}
    if name == "ag_queue_add_hash":
        item = add_hash(root, str(args.get("path") or ""), note=str(args.get("note") or ""))
        return {"added": item, "queue": load_queue(root)}
    if name == "ag_queue_add_unknown":
        item = add_unknown(
            root,
            note=str(args.get("note") or ""),
            scope=str(args.get("scope") or ""),
        )
        return {"added": item, "queue": load_queue(root)}
    if name == "ag_queue_run":
        return run_queue(root)
    raise ChainBroken(f"unknown tool {name}")


def serve() -> None:
    stdin = sys.stdin
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(msg, dict):
            continue
        reply = _handle(msg)
        if reply is None:
            continue
        sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
        sys.stdout.flush()
