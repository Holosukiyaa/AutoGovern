"""Read-only HTML table of critic events from AG_HOME sqlite."""
from __future__ import annotations

import html
import webbrowser
from pathlib import Path
from typing import Any

from .managed import ChainBroken, ag_home, load_managed, real_root
from .probe import list_probes
from .store import db_path, list_critic_events, list_probe_rows, list_switch_events, upsert_probe

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
    return html.escape(str(value or ""), quote=True)


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


def resolve_gui_root(explicit: str | None = None, *, reader=input) -> Path:
    if explicit and str(explicit).strip():
        return Path(str(explicit).strip())
    roots = enrolled_roots()
    if not roots:
        raise ChainBroken("no enrolled repos; pass a path to ag gui")
    if len(roots) == 1:
        return roots[0]
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
    raise ChainBroken("pick a listed number")


def html_path(root: Path) -> Path:
    repo = real_root(root)
    return ag_home() / "projects" / db_path(repo).parent.name / "critic-log.html"


def write_live(
    root: Path,
    *,
    phase: str,
    timings: dict[str, Any] | None = None,
    thinking: str = "",
    content: str = "",
) -> Path:
    repo = real_root(root)
    bits = []
    for key in ("tests_s", "probes_s", "critic_s", "total_s"):
        if timings and key in timings:
            bits.append(f"{key}={timings[key]}")
    timing_line = " ".join(bits) or "running"
    page = (
        "<!doctype html><meta charset='utf-8'><meta http-equiv='refresh' content='2'>"
        "<title>ag verify live</title>"
        "<style>body{font-family:sans-serif;margin:1.5rem}pre{white-space:pre-wrap;background:#111;color:#eee;padding:1rem}</style>"
        f"<h1>verify live</h1><p>phase={_cell(phase)}</p><p>{_cell(timing_line)}</p>"
        "<p>Five minutes is usually the enrolled tests, not DeepSeek. Thinking below streams during critic.</p>"
        f"<h2>thinking</h2><pre>{_cell(thinking[-20000:])}</pre>"
        f"<h2>content</h2><pre>{_cell(content[-8000:])}</pre>"
    )
    out = html_path(repo)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


def write_dashboard(root: Path, *, browse: bool = True) -> Path:
    repo = real_root(root)
    events = list_critic_events(repo, limit=200)
    rows = []
    for event in reversed(events):
        items = event.get("items") or []
        item_txt = "; ".join(
            f"{item.get('status')}:{item.get('name')}" for item in items if isinstance(item, dict)
        )
        rows.append(
            "<tr>"
            f"<td>{_cell(event.get('report_id'))}</td>"
            f"<td>{_cell(event.get('ts'))}</td>"
            f"<td>{_cell(event.get('outcome'))}</td>"
            f"<td>{_cell(event.get('model'))}</td>"
            f"<td>{_cell(event.get('task_id'))}</td>"
            f"<td>{_cell(event.get('reason'))}</td>"
            f"<td>{_cell(item_txt)}</td>"
            "</tr>"
        )
    body = "\n".join(rows) or "<tr><td colspan='7'>no critic_event rows</td></tr>"
    switch_events = list_switch_events(repo, limit=200)
    switch_rows = []
    for event in reversed(switch_events):
        switch_rows.append(
            "<tr>"
            f"<td>{_cell(event.get('report_id'))}</td>"
            f"<td>{_cell(event.get('ts'))}</td>"
            f"<td>{_cell(event.get('outcome'))}</td>"
            f"<td>{_cell(event.get('reason'))}</td>"
            "</tr>"
        )
    switch_body = "\n".join(switch_rows) or "<tr><td colspan='4'>no switch_event rows</td></tr>"
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
            f"<td>{_cell(probe.get('state'))}</td>"
            f"<td>{_cell(probe.get('quiet_count'))}</td>"
            f"<td>{_cell(probe.get('ttl_quiet_loops'))}</td>"
            f"<td>{_cell(', '.join(str(x) for x in (probe.get('area') or [])))}</td>"
            f"<td>{_cell(probe.get('exam_fragment'))}</td>"
            "</tr>"
        )
    probes_body = "\n".join(probe_rows) or "<tr><td colspan='6'>no probes</td></tr>"
    last = events[-1] if events else {}
    timings = last.get("timings") if isinstance(last.get("timings"), dict) else {}
    timing_bits = " ".join(f"{k}={v}" for k, v in timings.items()) or "no timings yet"
    think = str(last.get("thinking") or "")
    page = f"""<!doctype html>
<meta charset="utf-8">
<meta http-equiv="refresh" content="5">
<title>ag critic log</title>
<style>
body {{ font-family: sans-serif; margin: 1.5rem; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 2rem; }}
th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; vertical-align: top; }}
th {{ background: #f4f4f4; }}
.meta {{ color: #555; margin-bottom: 1rem; }}
pre {{ white-space: pre-wrap; background: #111; color: #eee; padding: 1rem; max-height: 24rem; overflow: auto; }}
</style>
<h1>ag critic log</h1>
<p class="meta">root={_cell(repo)} db={_cell(db_path(repo))} — sqlite critic_event + switch_event + probes. Refresh every 5s. Open this bat before ag_verify to watch thinking.</p>
<p class="meta">last timings: {_cell(timing_bits)} — tests_s is usually the long wait</p>
<h2>last critic thinking</h2>
<pre>{_cell(think[-20000:]) or "(none)"}</pre>
<table>
<thead><tr><th>report_id</th><th>ts</th><th>outcome</th><th>model</th><th>task</th><th>reason</th><th>items</th></tr></thead>
<tbody>
{body}
</tbody>
</table>
<h1>switch</h1>
<p class="meta">sw- rows from switch_event; critic thinking above is not the switch</p>
<table>
<thead><tr><th>report_id</th><th>ts</th><th>outcome</th><th>reason</th></tr></thead>
<tbody>
{switch_body}
</tbody>
</table>
<h1>probes</h1>
<p class="meta">exam_fragment only; observation is not shown</p>
<table>
<thead><tr><th>id</th><th>state</th><th>quiet</th><th>ttl</th><th>area</th><th>exam_fragment</th></tr></thead>
<tbody>
{probes_body}
</tbody>
</table>
"""
    out = html_path(repo)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    if browse:
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
