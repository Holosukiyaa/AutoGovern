"""Read-only HTML table of critic events from AG_HOME sqlite."""
from __future__ import annotations

import html
import json
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .managed import ChainBroken, ag_home, load_managed, real_root
from .probe import list_probes
from .store import db_path, list_critic_events, list_probe_rows, list_switch_events, load_task_timeline, project_dir, upsert_probe

TOOLS = [
    {
        "name": "ag_gui",
        "description": "Write a read-only HTML table of critic_event and switch_event rows from AG_HOME sqlite. Not a lane.",
        "inputSchema": {
            "type": "object",
            "properties": {"root": {"type": "string"}},
            "required": ["root"],
        },
    }
]


def _cell(value: object) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


_PHASE_ZH = {
    "start": "开工",
    "verify-tests": "验货·冒烟",
    "verify-probes": "验货·探针",
    "verify-critic": "验货·纠错",
    "verify-switch": "验货·开关",
    "finish": "交货成功",
    "finish-refused": "交货拒绝",
    "tests": "冒烟",
    "probes": "探针",
    "critic": "纠错",
    "switch": "开关",
}
_OUTCOME_ZH = {
    "passed": "通过",
    "pass": "通过",
    "rejected": "否决",
    "reject": "否决",
    "unavailable": "不可用",
    "allow": "放行",
    "deny": "拒绝",
    "denied": "拒绝",
    "undeclared": "未申报",
    "failed": "失败",
    "fail": "失败",
    "pending": "待定",
    "unproven": "未证明",
    "unknown": "未知",
    "uncertain": "不确定",
    "red": "红",
    "green": "绿",
    "skip": "跳过",
    "skipped": "跳过",
    "error": "出错",
    "void": "作废",
    "ok": "好",
    "success": "成功",
}
_STATE_ZH = {"armed": "武装", "archived": "冷藏", "quiet": "安静", "active": "在用"}
_TIMING_ZH = {
    "tests_s": "冒烟秒",
    "probes_s": "探针秒",
    "critic_s": "纠错秒",
    "switch_s": "开关秒",
    "total_s": "合计秒",
}
_REASON_ZH = {
    "not-configured": "未配置",
    "tests-failed": "冒烟失败，未问纠错",
    "andersen: same family": "安达信：同族不能阅卷",
    "merge": "合入失败",
}
_REASON_FRAG = (
    ("critic output is not JSON", "纠错输出不是结构化正文"),
    ("switch output is not JSON", "开关输出不是结构化正文"),
    ("output is not JSON", "输出不是结构化正文"),
    ("verdict must be pass|reject, got", "裁决必须是通过或否决，实际是"),
    ("items must be a non-empty list", "条目不能为空"),
    ("items must be a list", "条目必须是列表"),
    ("must be an object", "必须是对象"),
    (".status must be pass|fail", "的状态必须是通过或失败"),
    ("fail without path:line / portrait:… / probe:<id> evidence", "失败但没有路径:行号 / 画像: / 探针编号 证据"),
    ("verdict is reject but no item is fail", "裁决为否决但没有失败条目"),
    ("verdict is pass but some items are fail", "裁决为通过但有失败条目"),
    ("invalid-config: timeout must be an int", "配置无效：超时必须是整数"),
    ("invalid-config: AG_CRITIC_TIMEOUT must be an int", "配置无效：超时必须是整数"),
    ("void: ", "作废："),
    (" (作废)", ""),
    ("items[", "条目["),
    ("'unproven'", "「未证明」"),
    ("'pass'", "「通过」"),
    ("'reject'", "「否决」"),
    ("'fail'", "「失败」"),
)


def _zh_phase(value: object) -> str:
    key = str(value or "")
    return _PHASE_ZH.get(key, _PHASE_ZH.get(key.strip().casefold(), key))


def _zh_outcome(value: object) -> str:
    raw = str(value or "")
    key = raw.strip().casefold()
    if not key:
        return "无"
    return _OUTCOME_ZH.get(key, raw)


def _zh_state(value: object) -> str:
    raw = str(value or "")
    key = raw.strip().casefold()
    if not key:
        return "无"
    return _STATE_ZH.get(key, raw)


def _zh_reason(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "无"
    key = raw.casefold()
    if key in _REASON_ZH:
        return _REASON_ZH[key]
    if raw in _REASON_ZH:
        return _REASON_ZH[raw]
    text = raw
    for english, chinese in _REASON_FRAG:
        text = text.replace(english, chinese)
    return text


def _zh_model(value: object) -> str:
    key = str(value or "").strip()
    if not key:
        return "无"
    low = key.casefold()
    if "deepseek" in low:
        return "深度求索·闪速" if "flash" in low else "深度求索"
    if "grok" in low:
        return "工位模型"
    return key


def _zh_timings(timings: dict[str, Any] | None) -> str:
    if not timings:
        return "暂无耗时"
    bits = []
    for key, label in _TIMING_ZH.items():
        if key in timings:
            bits.append(f"{label}={timings[key]}")
    return " ".join(bits) or "暂无耗时"


def enrolled_roots() -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for row in load_managed().get("projects") or []:
        if not isinstance(row, dict):
            continue
        raw = row.get("real") or row.get("root")
        if not raw:
            continue
        path = Path(str(raw))
        if not path.is_dir():
            continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        found.append(path.resolve())
    return found


def _pick_tk(roots: list[Path]) -> Path | None:
    try:
        import tkinter as tk
    except Exception:
        return None
    chosen: list[Path] = []
    try:
        win = tk.Tk()
    except Exception:
        return None
    win.title("选择要查看的仓库")
    win.geometry("720x280")
    var = tk.StringVar(value=str(roots[0]))
    tk.Label(win, text="请选择已入学的仓库", anchor="w").pack(fill="x", padx=10, pady=(10, 4))
    for path in roots:
        tk.Radiobutton(win, text=str(path), variable=var, value=str(path), anchor="w", justify="left").pack(fill="x", padx=12)
    def ok() -> None:
        chosen.append(Path(var.get()))
        win.destroy()
    bar = tk.Frame(win)
    bar.pack(pady=12)
    tk.Button(bar, text="打开看板", command=ok).pack(side="left", padx=8)
    tk.Button(bar, text="取消", command=win.destroy).pack(side="left", padx=8)
    win.mainloop()
    return chosen[0] if chosen else None


def resolve_gui_root(explicit: str | None = None, *, reader=input) -> Path:
    if explicit and str(explicit).strip():
        return Path(str(explicit).strip())
    roots = enrolled_roots()
    if not roots:
        raise ChainBroken("没有已入学的仓库，请把路径拖到脚本上")
    if len(roots) == 1:
        return roots[0]
    picked = _pick_tk(roots)
    if picked is not None:
        return picked
    if not (sys.stdin and sys.stdin.isatty()):
        raise ChainBroken("未选择仓库")
    print("请输入编号后回车：", flush=True)
    for index, path in enumerate(roots, start=1):
        print(f"{index}. {path}", flush=True)
    raw = str(reader()).strip()
    if raw.isdigit():
        pick = int(raw)
        if 1 <= pick <= len(roots):
            return roots[pick - 1]
    for path in roots:
        if raw.lower() in str(path).lower():
            return path
    raise ChainBroken("请输入列表中的编号")


def resolve_dashboard_root(explicit: str | None = None) -> Path:
    if explicit and str(explicit).strip():
        return Path(str(explicit).strip())
    roots = enrolled_roots()
    if not roots:
        raise ChainBroken("没有已入学的仓库，请把路径拖到脚本上")
    return _active_root(roots) or roots[0]


def html_path(root: Path) -> Path:
    repo = real_root(root)
    return ag_home() / "projects" / db_path(repo).parent.name / "critic-log.html"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return blob if isinstance(blob, dict) else {}


def _active_task(root: Path) -> dict[str, Any]:
    repo = real_root(root)
    path = project_dir(repo) / "task.json"
    blob = _read_json(path)
    if not blob:
        return {}
    blob["state_path"] = str(path)
    return blob


def _active_root(roots: list[Path] | None = None) -> Path | None:
    candidates = roots if roots is not None else enrolled_roots()
    active = [(path, task) for path in candidates if (task := _active_task(path))]
    if not active:
        return None
    return max(active, key=lambda pair: Path(str(pair[1].get("state_path") or "")).stat().st_mtime)[0]


def _live_paths(task: dict[str, Any], root: Path) -> list[tuple[str, Path]]:
    repo = real_root(root)
    project = project_dir(repo)
    paths: list[tuple[str, Path]] = [
        ("Critic", project / "critic-live.jsonl"),
        ("Switch", project / "switch-live.jsonl"),
    ]
    worktree = Path(str(task.get("worktree") or ""))
    workers = worktree / ".ag-artifacts" / "workers"
    if workers.is_dir():
        for worker in workers.iterdir():
            if worker.is_dir() and (worker / "live.jsonl").is_file():
                paths.append((f"Worker {worker.name}", worker / "live.jsonl"))
    return paths


def _live_rows(paths: list[tuple[str, Path]], limit: int = 200) -> tuple[str, int]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for source, path in paths:
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        except OSError:
            continue
        for line in lines:
            try:
                blob = json.loads(line)
            except json.JSONDecodeError:
                blob = {"text": line}
            if isinstance(blob, dict):
                rows.append((source, blob))
    if not rows:
        return "<div class='empty'>暂无实时输出。任务进行中会自动出现。</div>", 0
    body = []
    for source, row in reversed(rows[-limit:]):
        text = str(row.get("text") or row.get("content") or row.get("reasoning") or row.get("summary") or "")
        phase = str(row.get("phase") or "")
        stamp = str(row.get("ts") or "")
        label = " · ".join(part for part in (source, phase, stamp) if part)
        body.append(f"<article><header>{_cell(label)}</header><pre>{_cell(text[-8000:]) or '无内容'}</pre></article>")
    return "\n".join(body), len(rows)


def _live_slots(root: Path, rows_per_slot: int = 24) -> list[dict[str, Any]]:
    task = _active_task(root)
    slots: list[dict[str, Any]] = []
    for source, path in _live_paths(task, root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-rows_per_slot:]
        except OSError:
            lines = []
        rows = []
        for line in lines:
            try:
                blob = json.loads(line)
            except json.JSONDecodeError:
                blob = {"text": line}
            if not isinstance(blob, dict):
                continue
            text = str(
                blob.get("text")
                or blob.get("content")
                or blob.get("reasoning")
                or blob.get("summary")
                or ""
            )
            rows.append(
                {
                    "phase": str(blob.get("phase") or ""),
                    "ts": str(blob.get("ts") or ""),
                    "text": text[-4000:],
                }
            )
        if source.startswith("Worker "):
            worker_id = source.removeprefix("Worker ")
            result_path = path.parent / "result.json"
            status = "running"
            failed = any(row["phase"] in {"timeout", "failed"} for row in rows)
            if failed:
                status = "failed"
            elif result_path.is_file():
                status = "exited"
            elif any(row["phase"] == "exit" for row in rows):
                status = "failed"
            detail = "已交付 result.json" if result_path.is_file() else "等待 result.json"
            if status == "failed" and not result_path.is_file():
                detail = "provider 已退出但 result.json 缺失"
        else:
            worker_id = ""
            status = "recent"
            detail = "最近一次 checker 输出"
        slots.append(
            {
                "id": source,
                "kind": "worker" if source.startswith("Worker ") else source.lower(),
                "worker_id": worker_id,
                "status": status,
                "detail": detail,
                "rows": rows,
            }
        )
    return slots


def _render_live_slots(slots: list[dict[str, Any]]) -> str:
    if not slots:
        return "<div class='empty'>暂无实时输出。任务进行中会自动出现。</div>"
    cards = []
    for slot in slots:
        body = []
        for row in slot.get("rows") or []:
            if not isinstance(row, dict):
                continue
            label = " · ".join(str(part) for part in (row.get("phase"), row.get("ts")) if part)
            text = str(row.get("text") or "")
            prefix = _cell(label + chr(10) if label else "")
            body.append(f"<pre>{prefix}{_cell(text) or '无内容'}</pre>")
        card_body = "".join(body) or "<pre>暂无输出</pre>"
        cards.append(
            "<article>"
            f"<header>{_cell(slot.get('id'))} · {_cell(slot.get('status'))}</header>"
            f"<p>{_cell(slot.get('detail'))}</p>{card_body}"
            "</article>"
        )
    return "\n".join(cards)


def _live_page(root: Path) -> str:
    return f"""<!doctype html>
<meta charset="utf-8">
<title>AG 实时对话</title>
<style>
body {{ margin: 0; background: #f5f5f5; }}
#live {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(22rem, 1fr)); gap: 1rem; align-items: start; padding: 1rem; }}
#live article {{ border: 1px solid #ddd; border-radius: 8px; overflow: hidden; background: #fff; }}
#live article header {{ background: #f4f4f4; color: #333; padding: 0.45rem 0.7rem; font-size: 0.9rem; }}
#live p {{ margin: 0.5rem 0.7rem; }}
#live pre {{ white-space: pre-wrap; background: #111; color: #eee; padding: 0.7rem; max-height: 18rem; overflow: auto; margin: 0; }}
.empty {{ border: 1px dashed #bbb; border-radius: 8px; color: #666; padding: 1rem; margin: 1rem; }}
</style>
<div id="live">{_render_live_slots(_live_slots(root))}</div>
"""


def write_live(
    root: Path,
    *,
    phase: str,
    timings: dict[str, Any] | None = None,
    thinking: str = "",
    content: str = "",
) -> Path:
    repo = real_root(root)
    timing_line = _zh_timings(timings)
    think_h = "开关思考" if phase == "switch" else "纠错思考" if phase == "critic" else "思考"
    stamps = []
    for step in load_task_timeline(repo).get("steps") or []:
        if not isinstance(step, dict):
            continue
        stamps.append(
            f"{_zh_phase(step.get('phase'))} {step.get('ts')} {step.get('seconds', '')} {step.get('report_id') or ''}".strip()
        )
    trail = "<br>".join(_cell(item) for item in stamps) or "（还没有步骤）"
    page = (
        "<!doctype html><meta charset='utf-8'><meta http-equiv='refresh' content='2'>"
        "<title>验货现场</title>"
        "<style>body{font-family:'微软雅黑',sans-serif;margin:1.5rem}pre{white-space:pre-wrap;background:#111;color:#eee;padding:1rem}</style>"
        f"<h1>验货现场</h1><p>当前阶段：{_cell(_zh_phase(phase))}</p><p>{_cell(timing_line)}</p>"
        f"<h2>时间线</h2><p>{trail}</p>"
        "<p>若合计很久，多半是入学冒烟测试，不是纠错思考。下方是当前席位的实时思考。</p>"
        f"<h2>{_cell(think_h)}</h2><pre>{_cell(thinking[-20000:]) or '无'}</pre>"
        f"<h2>正文</h2><pre>{_cell(content[-8000:]) or '无'}</pre>"
    )
    out = html_path(repo)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


def write_dashboard(root: Path, *, browse: bool = True) -> Path:
    repo = real_root(root)
    task = _active_task(root)
    live_body, live_count = _live_rows(_live_paths(task, root))
    events = list_critic_events(repo, limit=200)
    rows = []
    for event in reversed(events):
        items = event.get("items") or []
        item_txt = "；".join(
            f"{_zh_outcome(item.get('status'))}：{item.get('name')}" for item in items if isinstance(item, dict)
        )
        rows.append(
            "<tr>"
            f"<td>{_cell(event.get('report_id'))}</td>"
            f"<td>{_cell(event.get('ts'))}</td>"
            f"<td>{_cell(_zh_outcome(event.get('outcome')))}</td>"
            f"<td>{_cell(_zh_model(event.get('model')))}</td>"
            f"<td>{_cell(event.get('task_id') or '无')}</td>"
            f"<td>{_cell(_zh_reason(event.get('reason')))}</td>"
            f"<td>{_cell(item_txt or '无')}</td>"
            "</tr>"
        )
    body = "\n".join(rows) or "<tr><td colspan='7'>暂无纠错记录</td></tr>"
    switch_events = list_switch_events(repo, limit=200)
    switch_rows = []
    for event in reversed(switch_events):
        switch_rows.append(
            "<tr>"
            f"<td>{_cell(event.get('report_id'))}</td>"
            f"<td>{_cell(event.get('ts'))}</td>"
            f"<td>{_cell(_zh_outcome(event.get('outcome')))}</td>"
            f"<td>{_cell(_zh_reason(event.get('reason')))}</td>"
            "</tr>"
        )
    switch_body = "\n".join(switch_rows) or "<tr><td colspan='4'>暂无开关记录</td></tr>"
    listed = list_probes(repo, full=False)
    for probe in listed.get("probes") or []:
        if isinstance(probe, dict) and probe.get("id"):
            try:
                upsert_probe(repo, probe)
            except Exception:
                pass
    probe_rows = []
    for probe in list_probe_rows(repo):
        probe_rows.append(
            "<tr>"
            f"<td>{_cell(probe.get('id'))}</td>"
            f"<td>{_cell(_zh_state(probe.get('state')))}</td>"
            f"<td>{_cell(probe.get('quiet_count'))}</td>"
            f"<td>{_cell(probe.get('ttl_quiet_loops'))}</td>"
            f"<td>{_cell(', '.join(str(x) for x in (probe.get('area') or [])))}</td>"
            f"<td>{_cell(probe.get('exam_fragment'))}</td>"
            "</tr>"
        )
    probes_body = "\n".join(probe_rows) or "<tr><td colspan='6'>暂无探针</td></tr>"
    last = events[-1] if events else {}
    timings = last.get("timings") if isinstance(last.get("timings"), dict) else {}
    timing_bits = _zh_timings(timings if isinstance(timings, dict) else None)
    think = str(last.get("thinking") or "")
    timeline = load_task_timeline(repo)
    time_rows = []
    for step in timeline.get("steps") or []:
        if not isinstance(step, dict):
            continue
        rid = str(step.get("report_id") or step.get("critic_report_id") or "")
        sw = str(step.get("switch_report_id") or "")
        ids = " ".join(part for part in (rid, sw) if part)
        note = ids
        if not note and step.get("reason"):
            note = _zh_reason(step.get("reason"))
        elif not note and step.get("product"):
            note = _zh_outcome(step.get("product"))
        time_rows.append(
            "<tr>"
            f"<td>{_cell(_zh_phase(step.get('phase')))}</td>"
            f"<td>{_cell(step.get('ts'))}</td>"
            f"<td>{_cell(step.get('seconds') if step.get('seconds') not in (None, '') else '无')}</td>"
            f"<td>{_cell(note)}</td>"
            "</tr>"
        )
    time_body = "\n".join(time_rows) or "<tr><td colspan='4'>暂无任务步骤</td></tr>"
    page = f"""<!doctype html>
<meta charset="utf-8">
<title>治理看板</title>
<style>
body {{ font-family: "微软雅黑", sans-serif; margin: 1.5rem; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 2rem; }}
th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; vertical-align: top; }}
th {{ background: #f4f4f4; }}
.meta {{ color: #555; margin-bottom: 1rem; }}
pre {{ white-space: pre-wrap; background: #111; color: #eee; padding: 1rem; max-height: 24rem; overflow: auto; }}
.live-frame {{ width: 100%; height: 30rem; border: 0; }}
.empty {{ border: 1px dashed #bbb; border-radius: 8px; color: #666; padding: 1rem; }}
</style>
<h1>任务时间线</h1>
<p class="meta">任务编号 {_cell(timeline.get("task_id") or "无")}　账本 {_cell(timeline.get("path") or "无")}　（当前任务或上一轮已结束任务）</p>
<h1>实时对话</h1>
<p class="meta">自动发现当前任务。这里按 worker、critic、switch 分槽位显示，每个槽位保留最近 24 行；浏览器只刷新这块，不重画整页。</p>
<iframe id="live" class="live-frame" src="/live" title="AG 实时对话"></iframe>
<table>
<thead><tr><th>阶段</th><th>时间</th><th>秒</th><th>编号 / 说明</th></tr></thead>
<tbody>
{time_body}
</tbody>
</table>
<h1>纠错账</h1>
<p class="meta">仓库 {_cell(repo)}　数据库 {_cell(db_path(repo))}。实时槽位每 500ms 局部刷新；审计表由静态文件承载，需要手动重新生成。</p>
<p class="meta">最近耗时：{_cell(timing_bits)}。合计很久时，多半是冒烟测试。</p>
<h2>最近一次纠错思考</h2>
<p class="meta">以下为席位原文，界面不改写。</p>
<pre>{_cell(think[-20000:]) or "无"}</pre>
<table>
<thead><tr><th>编号</th><th>时间</th><th>结果</th><th>模型</th><th>任务</th><th>原因</th><th>条目</th></tr></thead>
<tbody>
{body}
</tbody>
</table>
<h1>开关账</h1>
<p class="meta">来自开关席。上面的纠错思考不是开关思考。</p>
<table>
<thead><tr><th>编号</th><th>时间</th><th>结果</th><th>原因</th></tr></thead>
<tbody>
{switch_body}
</tbody>
</table>
<h1>探针</h1>
<p class="meta">只显示病名，不显示尺的实现。</p>
<table>
<thead><tr><th>编号</th><th>状态</th><th>安静次数</th><th>寿命</th><th>范围</th><th>病名</th></tr></thead>
<tbody>
{probes_body}
</tbody>
</table>
"""
    out = html_path(repo)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    if browse:
        if os.name == "nt":
            os.startfile(str(out))  # type: ignore[attr-defined]
        else:
            webbrowser.open(out.as_uri())
    return out


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name != "ag_gui":
        raise ChainBroken(f"gui has no tool {name}")
    root = args.get("root")
    if not root:
        raise ChainBroken("root is required")
    path = write_dashboard(Path(str(root)), browse=False)
    return {"schema": "ag.gui.v1", "path": str(path), "reminder": "HTML reads sqlite, not a lane"}


def make_live_handler(root: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib interface
            path = self.path.split("?", 1)[0]
            if path == "/live":
                payload = _live_page(root).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Refresh", "0.5; url=/live")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if path not in ("/", "/index.html"):
                self.send_error(404)
                return
            path = write_dashboard(root, browse=False)
            page = path.read_text(encoding="utf-8")
            payload = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler



def serve_dashboard(root: Path, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    Handler = make_live_handler(root)

    for candidate_port in (port, 0):
        try:
            server = ThreadingHTTPServer((host, candidate_port), Handler)
            break
        except OSError:
            if candidate_port == 0:
                raise
            continue
    url = f"http://{host}:{server.server_port}/"
    print(url, flush=True)
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
