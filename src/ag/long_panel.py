"""A local browser view over the authoritative long-task API.

There is no browser authorization route. Every edit is an incremental core
operation with the exact revision the browser displayed.
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from typing import Any

from . import long_tasks
from .managed import ChainBroken

MAX_BODY = 128 * 1024


class PanelServer:
    """An already running loopback server; close it to release its socket."""

    def __init__(self, root: Path, goal_id: str, port: int = 0):
        self.root = Path(root).resolve()
        self.goal_id = str(goal_id)
        long_tasks.read_goal(self.root, self.goal_id)
        self.token = secrets.token_urlsafe(32)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), _handler(self))
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/"
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="ag-long-panel", daemon=True)
        self.thread.start()

    def serve_forever(self) -> None:
        """Wait for this already running panel (for the foreground CLI)."""
        try:
            while self.thread.is_alive():
                self.thread.join(timeout=0.5)
        except KeyboardInterrupt:
            self.close()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)

    def __enter__(self) -> "PanelServer":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def start_panel(root: Path, goal_id: str, *, port: int = 0, open_browser: bool = False) -> PanelServer:
    panel = PanelServer(root, goal_id, port)
    if open_browser:
        webbrowser.open(panel.url)
    return panel


def _handler(panel: PanelServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "AGPanel"

        def log_message(self, format: str, *args: Any) -> None:
            pass

        def _reply(self, code: int, value: Any, *, html: bool = False) -> None:
            body = value.encode("utf-8") if html else json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def _local(self) -> bool:
            try:
                peer = ipaddress.ip_address(self.client_address[0])
                return peer.is_loopback and self.headers.get("Host") == f"127.0.0.1:{panel.httpd.server_port}"
            except ValueError:
                return False

        def _error(self, exc: Exception) -> None:
            details = getattr(exc, "details", None)
            is_conflict = isinstance(exc, getattr(long_tasks, "LongTaskConflict", ()))
            self._reply(409 if is_conflict else 400, {"error": str(exc), "details": details})

        def do_GET(self) -> None:
            if not self._local():
                self._reply(403, {"error": "仅允许通过本机回环地址访问面板。"})
                return
            parsed = urlsplit(self.path)
            try:
                if parsed.path == "/":
                    self._reply(200, files("ag").joinpath("long_panel.html").read_text(encoding="utf-8"), html=True)
                elif parsed.path == "/api/session":
                    self._reply(200, {"token": panel.token, "goal_id": panel.goal_id})
                elif parsed.path == "/api/goal":
                    self._reply(200, long_tasks.read_goal(panel.root, panel.goal_id))
                elif parsed.path in {"/api/history", "/api/diff"}:
                    query = parse_qs(parsed.query, strict_parsing=True) if parsed.query else {}
                    if set(query) - {"since_revision"}:
                        raise ValueError("未知查询字段。")
                    since = int(query.get("since_revision", ["0"])[0])
                    if since < 0:
                        raise ValueError("修订号不能为负数。")
                    value = (long_tasks.goal_history(panel.root, panel.goal_id, since_revision=since)
                             if parsed.path == "/api/history" else long_tasks.goal_diff(panel.root, panel.goal_id, since))
                    self._reply(200, value)
                elif parsed.path == "/api/work-package":
                    self._reply(200, long_tasks.work_package(panel.root, panel.goal_id))
                else:
                    self._reply(404, {"error": "面板路径不存在。"})
            except (ValueError, KeyError, OSError, ChainBroken) as exc:
                self._error(exc)

        def do_POST(self) -> None:
            if not self._local() or self.headers.get("Origin") != panel.url.rstrip("/"):
                self._reply(403, {"error": "写入必须来自当前本机面板页面。"})
                return
            if not hmac.compare_digest(self.headers.get("X-AG-Panel-Token", ""), panel.token):
                self._reply(403, {"error": "面板会话已失效，请刷新页面。"})
                return
            if self.path != "/api/operations":
                self._reply(404, {"error": "面板不提供此操作或人工授权入口。"})
                return
            try:
                if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                    raise ValueError("请求必须为 JSON。")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    raise ValueError("操作内容为空或过长。")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict) or set(body) != {"expected_revision", "operation"}:
                    raise ValueError("需要所见修订号和一个增量操作。")
                if type(body["expected_revision"]) is not int or not isinstance(body["operation"], dict):
                    raise ValueError("增量操作格式错误。")
                operation = body["operation"]
                # Browser may prepare facts and proposals, never authorize, bind
                # delivery outcomes, or present self-claimed evidence as verified.
                allowed = {"add_fact", "update_fact", "add_plan", "update_plan", "add_investigation", "update_investigation", "add_capability", "update_capability", "add_dependency", "update_dependency", "propose_change", "set_return_to"}
                if operation.get("type") not in allowed:
                    raise ValueError("此操作须由对应 AG 入口执行；面板仅编辑普通事实、计划和待决提案。")
                result = long_tasks.apply_operation(panel.root, panel.goal_id, operation, body["expected_revision"], source={"kind": "local-panel", "ref": panel.goal_id, "text": "用户在本机目标面板提交的增量操作"})
                self._reply(200, result)
            except (ValueError, KeyError, TypeError, OSError, ChainBroken) as exc:
                self._error(exc)

    return Handler
