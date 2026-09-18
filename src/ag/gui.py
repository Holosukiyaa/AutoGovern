"""Read-only HTML table of critic events from AG_HOME sqlite."""
from __future__ import annotations

import html
import webbrowser
from pathlib import Path
from typing import Any

from .managed import ChainBroken, ag_home, real_root
from .probe import list_probes
from .store import db_path, list_critic_events, list_probe_rows, upsert_probe

TOOLS = [
    {
        "name": "ag_gui",
        "description": "Write a read-only HTML table of critic_event rows from AG_HOME sqlite. Not a lane.",
        "inputSchema": {
            "type": "object",
            "properties": {"root": {"type": "string"}},
            "required": ["root"],
        },
    }
]


def _cell(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


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
    page = f"""<!doctype html>
<meta charset="utf-8">
<title>ag critic log</title>
<style>
body {{ font-family: sans-serif; margin: 1.5rem; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 2rem; }}
th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; vertical-align: top; }}
th {{ background: #f4f4f4; }}
.meta {{ color: #555; margin-bottom: 1rem; }}
</style>
<h1>ag critic log</h1>
<p class="meta">root={_cell(repo)} db={_cell(db_path(repo))} — sqlite critic_event + probes, not the old strategy poster</p>
<table>
<thead><tr><th>report_id</th><th>ts</th><th>outcome</th><th>model</th><th>task</th><th>reason</th><th>items</th></tr></thead>
<tbody>
{body}
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
    out = ag_home() / "projects" / db_path(repo).parent.name / "critic-log.html"
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
