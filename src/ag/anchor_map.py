"""Generate long-task intent anchor SVG maps."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

_SLOT = 230
_START = 154
_TERMINAL = 140
_MARGIN = 50

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


def _text(value, limit):
    return str(value or "").strip()[:limit]


def _visual_width(text):
    return sum(2 if ord(char) > 127 else 1 for char in text)


def _wrap_anchor_text(value, max_width=34, max_lines=2):
    text = str(value or "").strip()
    if not text:
        return [""]
    units = text.split()
    if len(units) <= 1:
        units = list(text)
    lines = []
    current = ""
    for unit in units:
        candidate = unit if not current else current + (" " if len(text.split()) > 1 and " " in text else "") + unit
        if current and _visual_width(candidate) > max_width:
            lines.append(current)
            current = unit
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        kept = lines[:max_lines]
        kept[-1] = kept[-1][:-1] + "…" if len(kept[-1]) > 1 else "…"
        return kept
    return lines


def default_artifact_path(title: str) -> Path:
    from subprocess import DEVNULL, check_output

    root = Path.cwd()
    output = check_output(["git", "rev-parse", "--show-toplevel"], cwd=root, stderr=DEVNULL, text=True).strip()
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in title).strip("-")
    return Path(output) / ".ag-artifacts" / "anchor-maps" / f"{safe or 'anchor-map'}.svg"


def render_map(
    title: str,
    portrait: str,
    out: Path,
    *,
    anchors: list[dict[str, Any]] | None = None,
    current_anchor: str = "",
    guards: list[str] | None = None,
    defaults: list[str] | None = None,
) -> Path:
    if anchors is None:
        from .loop import parse_anchors

        anchors = parse_anchors(portrait)
    route_anchors = [item for item in anchors if _kind(item) not in {"blocking", "avoid"}]
    blockers = [item for item in anchors if _kind(item) == "blocking"]
    avoids = [item for item in anchors if _kind(item) == "avoid"]
    guards = [str(item).strip() for item in (guards or []) if str(item).strip()]
    defaults = [str(item).strip() for item in (defaults or []) if str(item).strip()]
    count = len(route_anchors)
    width = _MARGIN + _START + max(1, len(route_anchors)) * _SLOT + _TERMINAL + _MARGIN
    height = 430 if blockers or avoids or guards or defaults else 360
    center = 180
    current_anchor = str(current_anchor or "").strip()
    svg: list[str] = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">')
    svg.append('<style>')
    svg.append('.bg{fill:#0e1218}.panel{fill:#141b24;stroke:#252f3c}.route{fill:none;stroke:#4d9dd8;stroke-width:5}.node{fill:#182432;stroke:#4d9dd8;stroke-width:2}.hard{stroke:#e0b34a;stroke-width:3}.discoverable{stroke:#8b97a8;stroke-dasharray:7 7}.defaulted{stroke:#7f6ea8;stroke-dasharray:5 5}.obsolete{stroke:#4f5a68;stroke-dasharray:4 7}.terminal{fill:#173528;stroke:#3dbe8c;stroke-width:3}.start{fill:#182432;stroke:#6ea8ff}.title{fill:#e8eef6;font:700 22px "Microsoft YaHei",sans-serif}.text{fill:#d7e2ee;font:13px "Microsoft YaHei",sans-serif}.tag{fill:#4d9dd8;font:700 11px sans-serif}.hard-tag{fill:#e0b34a;font:700 11px sans-serif}.terminal-tag{fill:#3dbe8c;font:700 11px sans-serif}.warn{fill:#8b97a8;font:12px "Microsoft YaHei",sans-serif}.zone-title{fill:#d96d6d;font:700 14px "Microsoft YaHei",sans-serif}.current{stroke:#3dbe8c;stroke-width:4}.current-tag{fill:#3dbe8c;font:700 11px sans-serif}.current-badge{fill:#173528;stroke:#3dbe8c;stroke-width:2}')
    svg.append('</style>')
    svg.append(f'<rect class="bg" width="{width}" height="{height}" rx="18"/>')
    svg.append(f'<rect class="panel" x="20" y="20" width="{width - 40}" height="{height - 40}" rx="18"/>')
    svg.append(f'<text class="title" x="42" y="58">{escape(title)}</text>')
    svg.append(f'<text class="warn" x="42" y="82">锚点是注意力路线，不是计划；{count} 个锚点。{"超过 8 个，建议合并或拆任务。" if count > 8 else ""}</text>')
    x = _MARGIN
    svg.append(f'<rect class="start" x="{x}" y="145" width="110" height="72" rx="16"/>')
    svg.append(f'<text class="tag" x="{x + 18}" y="168">起点</text>')
    svg.append(f'<text class="text" x="{x + 18}" y="192">用户一句话</text>')
    x += _START
    for index, item in enumerate(route_anchors, 1):
        kind = _kind(item)
        cls = "node"
        tag = "tag"
        if kind == "hard":
            cls += " hard"
            tag = "hard-tag"
        elif kind in {"discoverable", "defaulted", "obsolete"}:
            cls += f" {kind}"
        svg.append(f'<line class="route" x1="{x - 25}" y1="{center}" x2="{x}" y2="{center}"/>')
        is_current = current_anchor and str(item.get("id") or "") == current_anchor
        if is_current:
            cls += " current"
        svg.append(f'<rect class="{cls}" x="{x}" y="138" width="205" height="92" rx="16"/>')
        svg.append(f'<text class="{tag}" x="{x + 18}" y="163">{escape(item.get("id") or f"a{index}")}</text>')
        wrapped = _wrap_anchor_text(item.get("text"), max_width=34, max_lines=2)
        svg.append(f'<text class="text" x="{x + 18}" y="180">{escape(wrapped[0])}</text>')
        if len(wrapped) > 1:
            svg.append(f'<text class="text" x="{x + 18}" y="197">{escape(wrapped[1])}</text>')
        svg.append(f'<text class="{"current-tag" if is_current else "warn"}" x="{x + 18}" y="212">{escape(_KIND_LABELS[kind])}</text>')
        if is_current:
            svg.append(f'<rect class="current-badge" x="{x + 122}" y="147" width="70" height="21" rx="10"/>')
            svg.append(f'<text class="current-tag" x="{x + 132}" y="162">当前</text>')
        x += _SLOT
    svg.append(f'<line class="route" x1="{x - 25}" y1="{center}" x2="{x}" y2="{center}"/>')
    svg.append(f'<rect class="terminal" x="{x}" y="140" width="140" height="72" rx="18"/>')
    svg.append('<text class="terminal-tag" x="' + str(x + 18) + '" y="163">终点</text>')
    svg.append(f'<text class="text" x="{x + 18}" y="187">任务目标</text>')
    if blockers or avoids or guards or defaults:
        sections = [("阻塞未知：不问清不开工", [str(item.get("text") or "") for item in blockers]), ("避让区：偏离即披露", [str(item.get("text") or "") for item in avoids]), ("GUARDS：验收时必须成立", guards), ("DEFAULTS：默认选择，可协商调整", defaults)]
        section_x = 50
        active_sections = [(title_text, rows) for title_text, rows in sections if rows]
        section_width = max(220, min(300, (width - 100) // max(1, len(active_sections))))
        for title_text, rows in active_sections:
            svg.append(f'<text class="zone-title" x="{section_x}" y="300">{escape(title_text[:18])}</text>')
            for index, item in enumerate(rows[:6]):
                svg.append(f'<text class="warn" x="{section_x}" y="{324 + index * 20}">· {escape(_text(item, 28))}</text>')
            section_x += section_width
        if len(blockers) > 6 or len(avoids) > 6 or len(guards) > 6 or len(defaults) > 6:
            svg.append('<text class="warn" x="50" y="410">下方只显示前 6 条；完整清单仍保存在任务数据中。</text>')
    svg.append('</svg>')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(svg), encoding="utf-8")
    return out


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
