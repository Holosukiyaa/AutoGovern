"""Unicode intent-anchor maps. No SVG."""
from __future__ import annotations

from pathlib import Path
from typing import Any

_KIND_LABELS = {
    "soft": "软锚点",
    "hard": "硬锚点",
    "discoverable": "可查未知",
    "blocking": "阻塞未知",
    "defaulted": "已定默认",
    "avoid": "避让区",
    "obsolete": "已失效",
}


def _kind(item):
    kind = str(item.get("kind") or "").strip()
    return kind if kind in _KIND_LABELS else ("hard" if item.get("hard") else "soft")


def default_artifact_path(title: str) -> Path:
    from subprocess import DEVNULL, check_output

    root = Path.cwd()
    output = check_output(["git", "rev-parse", "--show-toplevel"], cwd=root, stderr=DEVNULL, text=True).strip()
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in title).strip("-")
    return Path(output) / ".ag-artifacts" / "anchor-maps" / f"{safe or 'anchor-map'}.txt"


def write_unicode(
    title: str,
    portrait: str,
    out: Path,
    *,
    anchors: list[dict[str, Any]] | None = None,
    current_anchor: str = "",
    guards: list[str] | None = None,
    defaults: list[str] | None = None,
) -> Path:
    """Write one Unicode intent map. An .svg destination is stored as .txt."""
    if anchors is None:
        from .loop import parse_anchors

        anchors = parse_anchors(portrait)
    destination = Path(out)
    if destination.suffix.lower() == ".svg":
        destination = destination.with_suffix(".txt")
    text = render_unicode(title, anchors or [], current_anchor, guards, defaults)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    return destination


def render_unicode(
    title: str,
    anchors: list[dict[str, Any]],
    current_anchor: str = "",
    guards: list[str] | None = None,
    defaults: list[str] | None = None,
) -> str:
    current_anchor = str(current_anchor or "").strip()
    symbols = {
        "soft": "◇",
        "hard": "■",
        "discoverable": "?",
        "blocking": "?",
        "defaulted": "◇",
        "avoid": "x",
        "obsolete": "x",
    }
    lines = [f"◆ {title}", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", "START", "  用户一句话", "  │"]
    route_anchors = [item for item in anchors if _kind(item) not in {"blocking", "avoid"}]
    for item in route_anchors:
        kind = _kind(item)
        symbol = symbols.get(kind, "◇")
        anchor_id = str(item.get("id") or "")
        current = " · 当前注意力" if current_anchor and anchor_id == current_anchor else ""
        lines.extend(
            [
                f"  ▼",
                f"{symbol} {anchor_id} · {kind.upper()}{current}",
                f"  {str(item.get('text') or '').strip()}",
                "  │",
            ]
        )
    lines.extend(["  ▼", "● END", "  任务目标", ""])
    blockers = [item for item in anchors if _kind(item) == "blocking"]
    avoids = [item for item in anchors if _kind(item) == "avoid"]
    if blockers:
        lines.extend(["x BLOCKING", *[f"  {item.get('text')}" for item in blockers], ""])
    if avoids:
        lines.extend(["x AVOID", *[f"  {item.get('text')}" for item in avoids], ""])
    guards = [str(item).strip() for item in (guards or []) if str(item).strip()]
    defaults = [str(item).strip() for item in (defaults or []) if str(item).strip()]
    if guards:
        lines.extend(["■ GUARDS", *[f"  {item}" for item in guards], ""])
    if defaults:
        lines.extend(["◇ DEFAULTS", *[f"  {item}" for item in defaults], ""])
    lines.extend(["图例", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", "◇ soft  ■ hard  ? unknown  x avoid/blocking  ● terminal", "■ guards 独立验收规则  ◇ defaults 可协商默认"])
    return "\n".join(lines)
