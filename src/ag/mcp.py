"""stdio MCP. Four lanes; only ship tools are live."""
from __future__ import annotations

import json
import sys
from typing import Any

from . import __version__
from . import catalog, gui
from .lanes import call as lane_call
from .lanes import tools as lane_tools
from .managed import ChainBroken

PROTOCOL = "2024-11-05"
INSTRUCTIONS = (
    "ag has four lanes that must not mix: ship (交货), heal (治病), lift (抬正确率), see (看见). "
    "Only ship may set product or refuse finish. "
    "File-changing work: ag_status → ag_start → write ONLY in worktree.path → ag_verify → ag_finish. "
    "ag_verify runs the enrolled test command. process complete is not product passed. "
    "If no test command is enrolled, product stays undeclared. "
    "Git hook refuses commits on canonical, including git commit --no-verify. "
    "This server does not intercept host Write; edits on canonical dirty it and start/finish refuse. "
    "ag_usage (see) counts how often each ship item helped or blocked; it is not product green. "
    "ag_gui writes a read-only HTML view; HTML is not a lane and not the core. "
    "ag_lift / ag_see are advice. ag_heal is stacked-door treatment and is NOT on the delivery path: "
    "do not run it until stacked doors are found; it must not become a finish gate. "
    "ag_plug on/off/list toggles pluggable lane-seq rows; ship core cannot be unplugged. "
    "Read-only critic: do not write product files, do not finish, do not git commit, and do not open a worktree. "
    "Insert a probe only via ag_probe_insert with already-seen evidence; ag_critic_pack is an exam pack, not a worker ticket. "
    "ag_critic_run does one read-only chat on that pack (no tools). "
    "unavailable or rejected does not refuse finish. "
    "ag_verify may attach one read-only critic; it does not refuse finish."
)
TOOLS = lane_tools() + gui.TOOLS + catalog.TOOLS


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
                "instructions": INSTRUCTIONS,
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
    if any(str(item["name"]) == name for item in gui.TOOLS):
        return gui.call(name, args)
    if any(str(item["name"]) == name for item in catalog.TOOLS):
        return catalog.call(name, args)
    return lane_call(name, args)


def _reconfigure_utf8(stream: Any) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        pass


def _read_message(reader: Any) -> dict[str, Any] | None:
    first = reader.readline()
    if first == "":
        return None
    if first.lower().startswith("content-length:"):
        length = int(first.split(":", 1)[1].strip())
        while True:
            line = reader.readline()
            if line in ("", "\n", "\r\n"):
                break
        body = reader.read(length)
        payload = json.loads(body)
        return payload if isinstance(payload, dict) else None
    text = first.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_message(writer: Any, payload: dict[str, Any]) -> None:
    # Grok stdio MCP parses each stdout line as JSON. LSP Content-Length
    # framing makes initialize fail with "expected value at line 1 column 1".
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    raw = getattr(writer, "buffer", None)
    if raw is not None:
        raw.write(line.encode("utf-8"))
        raw.flush()
        return
    writer.write(line)
    writer.flush()


def serve(stdin: Any | None = None, stdout: Any | None = None) -> None:
    reader = stdin or sys.stdin
    writer = stdout or sys.stdout
    if stdin is None:
        _reconfigure_utf8(sys.stdin)
    if stdout is None:
        _reconfigure_utf8(sys.stdout)
    while True:
        try:
            message = _read_message(reader)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return
        if message is None:
            return
        try:
            reply = _handle(message)
        except Exception as exc:
            req_id = message.get("id")
            if req_id is None:
                continue
            reply = _err(req_id, str(exc))
        if reply is None:
            continue
        _write_message(writer, reply)
