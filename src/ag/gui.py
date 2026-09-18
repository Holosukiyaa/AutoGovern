"""Read-only HTML table of critic events from AG_HOME sqlite."""
from __future__ import annotations

import html
import webbrowser
from pathlib import Path
from typing import Any

from .managed import ChainBroken, ag_home, real_root
from .store import db_path, list_critic_events

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
            f"<td>{_cell(event.get('ts'))}</td>"
            f"<td>{_cell(event.get('outcome'))}</td>"
            f"<td>{_cell(event.get('model'))}</td>"
            f"<td>{_cell(event.get('task_id'))}</td>"
            f"<td>{_cell(event.get('reason'))}</td>"
            f"<td>{_cell(item_txt)}</td>"
            "</tr>"
        )
    body = "\n".join(rows) or "<tr><td colspan='6'>no critic_event rows</td></tr>"
    page = f"""<!doctype html>
<meta charset="utf-8">
<title>ag critic log</title>
<style>
body {{ font-family: sans-serif; margin: 1.5rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; vertical-align: top; }}
th {{ background: #f4f4f4; }}
.meta {{ color: #555; margin-bottom: 1rem; }}
</style>
<h1>ag critic log</h1>
<p class="meta">root={_cell(repo)} db={_cell(db_path(repo))} — sqlite critic_event, not the old strategy poster</p>
<table>
<thead><tr><th>ts</th><th>outcome</th><th>model</th><th>task</th><th>reason</th><th>items</th></tr></thead>
<tbody>
{body}
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
