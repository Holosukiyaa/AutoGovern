"""Local GUI for other projects' probe status. Not a probe on ag itself."""
from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .checkup import checkup
from .gui_ui import APP_JS, INDEX_HTML, LAYOUT_CSS
from .managed import add_project, load_managed, project_snapshot
from .queue import ChainBroken, add_exists, add_hash, add_unknown, run_queue
from .report import dashboard_view, problems

HOST = "127.0.0.1"
PORT = 7420


def _page(title: str, body: str) -> bytes:
    doc = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
body {{ font-family: sans-serif; margin: 1.5rem; max-width: 52rem; }}
table {{ border-collapse: collapse; width: 100%; }}
td, th {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; }}
.ok {{ color: #0a0; }} .bad {{ color: #a00; }} .skip {{ color: #888; }}
form {{ margin: 1rem 0; }}
input[type=text] {{ width: 24rem; }}
</style></head><body>
<p><a href="/">ag 管理的项目</a></p>
{body}
</body></html>"""
    return doc.encode("utf-8")


def _status(item: dict) -> str:
    if item.get("unverifiable") or item.get("kind") == "unknown":
        return '<span class="skip">无法验证</span>'
    if item.get("skipped"):
        return '<span class="skip">未跑</span>'
    if item.get("trusted"):
        return '<span class="ok">绿</span>'
    if item.get("red_ok") is False or item.get("green_ok") is False:
        return '<span class="bad">红</span>'
    return '<span class="skip">无记录</span>'


def _rate_text(rate: float | None) -> str:
    if rate is None:
        return "尚无探针，可信率未知"
    pct = f"{rate * 100:.0f}%"
    return f"可信率 {pct}（提醒我和 AI，不拦截业务）"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _send(self, payload: bytes, status: int = 200, content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        blob = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(blob, status, "application/json; charset=utf-8")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(INDEX_HTML.encode("utf-8"))
            return
        if parsed.path == "/ui/layout.css":
            self._send(LAYOUT_CSS.encode("utf-8"), content_type="text/css; charset=utf-8")
            return
        if parsed.path == "/ui/app.js":
            self._send(APP_JS.encode("utf-8"), content_type="text/javascript; charset=utf-8")
            return
        if parsed.path == "/api/projects":
            rows = []
            for item in load_managed().get("projects") or []:
                if isinstance(item, dict) and item.get("root"):
                    rows.append({"root": item["root"]})
            self._send_json({"projects": rows})
            return
        if parsed.path == "/api/view":
            root = (parse_qs(parsed.query).get("root") or [""])[0]
            self._send_json(dashboard_view(Path(unquote(root))))
            return
        if parsed.path == "/p":
            qs = parse_qs(parsed.query)
            root = (qs.get("root") or [""])[0]
            self._send(_detail(root))
            return
        self._send(_page("not found", "<p>not found</p>"), 404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8")
        parsed = urlparse(self.path)
        if parsed.path in {"/api/run", "/api/checkup"}:
            try:
                body = json.loads(raw or "{}")
                root = Path(str(body.get("root") or ""))
                if parsed.path == "/api/run":
                    run_queue(root)
                else:
                    checkup(root, insert=True)
                self._send_json({"ok": True, "root": str(root)})
            except (ChainBroken, OSError, ValueError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, 400)
            return
        form = parse_qs(raw)
        try:
            if parsed.path == "/add-project":
                root = (form.get("root") or [""])[0]
                add_project(Path(unquote(root)))
                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()
                return
            if parsed.path == "/add-exists":
                root = (form.get("root") or [""])[0]
                rel = (form.get("path") or [""])[0]
                add_exists(Path(unquote(root)), rel)
                self.send_response(303)
                self.send_header("Location", "/p?root=" + root)
                self.end_headers()
                return
            if parsed.path == "/add-hash":
                root = (form.get("root") or [""])[0]
                rel = (form.get("path") or [""])[0]
                add_hash(Path(unquote(root)), rel)
                self.send_response(303)
                self.send_header("Location", "/p?root=" + root)
                self.end_headers()
                return
            if parsed.path == "/run":
                root = (form.get("root") or [""])[0]
                run_queue(Path(unquote(root)))
                self.send_response(303)
                self.send_header("Location", "/p?root=" + root)
                self.end_headers()
                return
            if parsed.path == "/checkup":
                root = (form.get("root") or [""])[0]
                checkup(Path(unquote(root)), insert=True)
                self.send_response(303)
                self.send_header("Location", "/p?root=" + root)
                self.end_headers()
                return
            if parsed.path == "/add-unknown":
                root = (form.get("root") or [""])[0]
                note = (form.get("note") or [""])[0]
                add_unknown(Path(unquote(root)), note=unquote(note))
                self.send_response(303)
                self.send_header("Location", "/p?root=" + root)
                self.end_headers()
                return
        except (ChainBroken, OSError, ValueError) as exc:
            self._send(_page("error", f"<p class='bad'>{html.escape(str(exc))}</p>"), 400)
            return
        self._send(_page("not found", "<p>not found</p>"), 404)


def _index() -> bytes:
    rows = []
    for item in load_managed().get("projects") or []:
        if not isinstance(item, dict):
            continue
        root = str(item.get("root") or "")
        snap = project_snapshot(Path(root))
        n = len(snap["items"])
        href = "/p?root=" + html.escape(root)
        rows.append(
            f"<tr><td><a href='{href}'>{html.escape(root)}</a></td>"
            f"<td>{n} 项</td><td>{html.escape(_rate_text(snap.get('trust_rate')))}</td></tr>"
        )
    table = "<p>还没有项目。</p>" if not rows else (
        "<table><tr><th>项目</th><th>项</th><th>可信率</th></tr>"
        + "".join(rows)
        + "</table>"
    )
    body = f"""<h1>别人的项目</h1>
{table}
<form method="post" action="/add-project">
<label>登记一个目录 <input type="text" name="root" required></label>
<button type="submit">登记</button>
</form>
<p>探针写在对方的 .ag/queue.json。ag 自己不插针。</p>"""
    return _page("ag", body)


def _detail(root: str) -> bytes:
    snap = project_snapshot(Path(root))
    issue = problems(Path(root))
    advice = checkup(Path(root), insert=False)
    issue_rows = []
    for row in issue.get("problems") or []:
        blame = row.get("blame") if isinstance(row.get("blame"), dict) else {}
        issue_rows.append(
            "<tr>"
            f"<td class='bad'>{html.escape(str(row.get('kind')))}</td>"
            f"<td>{html.escape(str(row.get('path') or ''))}</td>"
            f"<td>{html.escape(str(row.get('problem') or ''))}</td>"
            f"<td>run {html.escape(str(blame.get('run_id') or ''))} git {html.escape(str(blame.get('git_head') or ''))} {html.escape(str(blame.get('evidence') or ''))}</td>"
            "</tr>"
        )
    issue_table = "<p class='ok'>声明过的针里没有红/未跑/无法验证。</p>" if not issue_rows else (
        "<table><tr><th>类型</th><th>代码位置</th><th>问题</th><th>追责</th></tr>"
        + "".join(issue_rows)
        + "</table>"
    )
    hint_rows = []
    for row in advice.get("suggestions") or []:
        hint_rows.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('kind')))}</td>"
            f"<td>{html.escape(str(row.get('path') or ''))}</td>"
            f"<td>{html.escape(str(row.get('claim') or ''))}</td>"
            "</tr>"
        )
    hint_table = "<p>没有行数/胶水建议。</p>" if not hint_rows else (
        "<table><tr><th>建议</th><th>位置</th><th>说明</th></tr>"
        + "".join(hint_rows)
        + "</table>"
    )
    rows = []
    for item in snap["items"]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('kind')))}</td>"
            f"<td>{html.escape(str(item.get('path') or ''))}</td>"
            f"<td>{html.escape(str(item.get('note') or ''))}</td>"
            f"<td>{html.escape(str((item.get('speech') or {}).get('breadth') or ''))}</td>"
            f"<td>{html.escape(str((item.get('speech') or {}).get('claim') or ''))}</td>"
            f"<td>{_status(item)}</td>"
            "</tr>"
        )
    table = "<p>还没有探针。</p>" if not rows else (
        "<table><tr><th>种类</th><th>路径</th><th>说明</th><th>范围</th><th>能说什么</th><th>上次</th></tr>"
        + "".join(rows)
        + "</table>"
    )
    enc = html.escape(snap["root"])
    last = snap.get("last_run") if isinstance(snap.get("last_run"), dict) else {}
    run_line = ""
    if last.get("run_id"):
        run_line = (
            f"<p>上次证据 run {html.escape(str(last.get('run_id')))} "
            f"git {html.escape(str(last.get('git_head') or '(无 git)'))} "
            f"{html.escape(str(last.get('at') or ''))}</p>"
        )
    if snap.get("stale"):
        run_line += "<p class='bad'>证据过期：当前 HEAD 与上次 git_head 不一致，旧绿不能当现在的。</p>"
    body = f"""<h1>{enc}</h1>
<p>{html.escape(_rate_text(snap.get('trust_rate')))}</p>
<p>声明：精确 {int((snap.get('declared') or {}).get('precise') or 0)} · 较广 {int((snap.get('declared') or {}).get('broad') or 0)} · 无法验证 {int((snap.get('declared') or {}).get('wide') or 0)}（没有全仓库覆盖率）</p>
{run_line}
<h2>有问题的代码（追责）</h2>
{issue_table}
<h2>反向开发建议（不是验证）</h2>
{hint_table}
<p>队列文件 {html.escape(snap['queue'])} · 历史 .ag/runs.jsonl</p>
{table}
<form method="post" action="/run">
<input type="hidden" name="root" value="{enc}">
<button type="submit">跑全部探针</button>
</form>
<form method="post" action="/checkup">
<input type="hidden" name="root" value="{enc}">
<button type="submit">反向开发插针</button>
</form>
<form method="post" action="/add-exists">
<input type="hidden" name="root" value="{enc}">
<label>exists 单个文件 <input type="text" name="path" required></label>
<button type="submit">加高信任针</button>
</form>
<form method="post" action="/add-hash">
<input type="hidden" name="root" value="{enc}">
<label>hash 钉死文件 <input type="text" name="path" required></label>
<button type="submit">钉字节</button>
</form>
<form method="post" action="/add-unknown">
<input type="hidden" name="root" value="{enc}">
<label>无法验证的说明 <input type="text" name="note" required></label>
<button type="submit">标明无法验证</button>
</form>"""
    return _page(snap["root"], body)


def serve(host: str = HOST, port: int = PORT) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"ag gui http://{host}:{port}", flush=True)
    httpd.serve_forever()
