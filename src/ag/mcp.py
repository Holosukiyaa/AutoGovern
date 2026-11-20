"""stdio MCP. Four lanes; only ship tools are live."""
from __future__ import annotations

import json
import sys
from typing import Any

from . import __version__
from . import catalog
from .lanes import call as lane_call
from .lanes import tools as lane_tools
from .managed import ChainBroken

PROTOCOL = "2024-11-05"
INSTRUCTIONS = (
    "ag has three lanes that must not mix: ship (交货), lift (抬正确率), see (看见). "
    "Only ship may set product or refuse finish. "
    "File-changing work: ag_status → ag_start → write ONLY in worktree.path → ag_verify → ag_finish. "
    "ag_start reads <AG_HOME>/projects/<key>/ticket.md. "
    "the ticket never lives in the project tree. "
    "Single tickets require personal confirm-map per ticket. "
    "AI must never call ag_confirm_map or edit approval state. "
    "Before T4, changing a confirmed ticket requires ag_abandon (candidate preserved under refs/ag/abandoned/<task_id>) and a new ticket. "
    "For long-ticket-retired use ag_abandon; archived long data stays untouched in AG_HOME without migration. "
    "ag_delivery is a read-only task query shared with CLI delivery, including archived tasks. "
    "Keep the complete goal and remaining outcomes; internal phases do not require new tickets. "
    "Explicit continuation_of carries the common goal, contribution and remaining outcomes to an independently delivered successor. "
    "ag_verify selects this ticket's actual .ag-check scripts plus declared project checks, then probes and one switch review. "
    "The switch prompt is filled with the red lines sealed at start. "
    "process complete is not product passed. "
    "Unconfigured switch does not refuse finish. No enrolled tests and switch allow → product undeclared. "
    "Git hook refuses commits on canonical, including git commit --no-verify. "
    "This server does not intercept host Write; edits on canonical dirty it and start/finish refuse. "
    "While a task is open, tracked canonical files are frozen: Windows uses ACL deny-write; other systems use the read-only bit. "
    "ag_usage (see) counts how often each ship item helped or blocked; it is not product green. "
    "ag_lift / ag_see are advice. "
    "ag_plug on/off/list toggles pluggable lane-seq rows; ship core cannot be unplugged. "
    "Read-only critic: do not write product files, do not finish, do not git commit, and do not open a worktree. "
    "Insert a probe only via ag_probe_insert with already-seen evidence; ag_critic_pack is an exam pack, not a worker ticket. "
    "ag_critic_run does one read-only chat on that pack (no tools). "
    "Path-hit probe red, enrolled tests failing, or a configured switch that is not passed refuse finish. "
    "The critic compatibility field mirrors the switch receipt and must not be counted twice. "
    "Cite task_id, switch.report_id (sw-), candidate and actual check evidence. General suggestions are advisories; concrete violations and missing critical evidence remain blockers. "
)
TOOLS = lane_tools() + catalog.TOOLS


def _ok(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


PARSE_ERROR = -32700
INVALID_REQUEST = -32600


def _err(req_id: Any, message: str, code: int = -32000) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


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
            from .history import command_scope

            with command_scope():
                text = json.dumps(_call(name, args), ensure_ascii=False, indent=2)
        except (ChainBroken, OSError, TypeError, ValueError) as exc:
            details = getattr(exc, "details", None)
            message = json.dumps({"error": str(exc), "details": details}, ensure_ascii=False) if details else str(exc)
            return _ok(
                req_id,
                {"content": [{"type": "text", "text": message}], "isError": True},
            )
        return _ok(req_id, {"content": [{"type": "text", "text": text}]})
    if req_id is None:
        return None
    return _err(req_id, f"unknown method {method}")


def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
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


class BadMessage(ValueError):
    """A request that cannot be served; answered with id=null and the JSON-RPC code."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _bytes(chunk: Any) -> bytes:
    return chunk.encode("utf-8") if isinstance(chunk, str) else chunk


def _read_message(reader: Any) -> dict[str, Any] | None:
    """Next request object, None at EOF. Blank lines are skipped; bad input raises BadMessage."""
    first = b""
    while not first.strip():
        first = _bytes(reader.readline())
        if not first:
            return None
    if first.lower().startswith(b"content-length:"):
        try:
            length = int(first.split(b":", 1)[1].strip())
        except ValueError:
            raise BadMessage(PARSE_ERROR, "parse error: invalid Content-Length header") from None
        while _bytes(reader.readline()).strip():
            pass
        first = _bytes(reader.read(length))
    try:
        payload = json.loads(first.decode("utf-8"))
    except ValueError:  # includes invalid UTF-8
        raise BadMessage(PARSE_ERROR, "parse error: not valid UTF-8 JSON") from None
    if not isinstance(payload, dict):
        raise BadMessage(INVALID_REQUEST, "invalid request: expected a JSON object")
    return payload


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
    # Read raw bytes: a bad byte must cost one -32700 reply, not the stream.
    reader = stdin or sys.stdin.buffer
    writer = stdout or sys.stdout
    if stdout is None:
        _reconfigure_utf8(sys.stdout)
    while True:
        try:
            message = _read_message(reader)
        except BadMessage as exc:
            _write_message(writer, _err(None, str(exc), exc.code))
            continue
        except OSError:
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
