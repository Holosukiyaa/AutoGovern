"""Generate long-task intent anchor SVG maps."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from .loop import parse_anchors

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


def default_artifact_path(title: str) -> Path:
    from subprocess import DEVNULL, check_output

    root = Path.cwd()
    output = check_output(["git", "rev-parse", "--show-toplevel"], cwd=root, stderr=DEVNULL, text=True).strip()
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in title).strip("-")
    return Path(output) / ".ag-artifacts" / "anchor-maps" / f"{safe or 'anchor-map'}.svg"


def render_map(title: str, portrait: str, out: Path) -> Path:
    anchors = parse_anchors(portrait)
    route_anchors = [item for item in anchors if _kind(item) not in {"blocking", "avoid"}]
    blockers = [item for item in anchors if _kind(item) == "blocking"]
    avoids = [item for item in anchors if _kind(item) == "avoid"]
    count = len(anchors)
    width = _MARGIN + _START + max(1, len(route_anchors)) * _SLOT + _TERMINAL + _MARGIN
    height = 430 if blockers or avoids else 360
    center = 180
    svg: list[str] = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">')
    svg.append('<style>')
    svg.append('.bg{fill:#0e1218}.panel{fill:#141b24;stroke:#252f3c}.route{fill:none;stroke:#4d9dd8;stroke-width:5}.node{fill:#182432;stroke:#4d9dd8;stroke-width:2}.hard{stroke:#e0b34a;stroke-width:3}.discoverable{stroke:#8b97a8;stroke-dasharray:7 7}.defaulted{stroke:#7f6ea8;stroke-dasharray:5 5}.obsolete{stroke:#4f5a68;stroke-dasharray:4 7}.terminal{fill:#173528;stroke:#3dbe8c;stroke-width:3}.start{fill:#182432;stroke:#6ea8ff}.title{fill:#e8eef6;font:700 22px "Microsoft YaHei",sans-serif}.text{fill:#d7e2ee;font:13px "Microsoft YaHei",sans-serif}.tag{fill:#4d9dd8;font:700 11px sans-serif}.hard-tag{fill:#e0b34a;font:700 11px sans-serif}.terminal-tag{fill:#3dbe8c;font:700 11px sans-serif}.warn{fill:#8b97a8;font:12px "Microsoft YaHei",sans-serif}.zone-title{fill:#d96d6d;font:700 14px "Microsoft YaHei",sans-serif}')
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
        svg.append(f'<rect class="{cls}" x="{x}" y="140" width="205" height="82" rx="16"/>')
        svg.append(f'<text class="{tag}" x="{x + 18}" y="163">{escape(item.get("id") or f"a{index}")}</text>')
        svg.append(f'<text class="text" x="{x + 18}" y="187">{escape(_text(item.get("text"), 14))}</text>')
        svg.append(f'<text class="warn" x="{x + 18}" y="208">{escape(_KIND_LABELS[kind])}</text>')
        x += _SLOT
    svg.append(f'<line class="route" x1="{x - 25}" y1="{center}" x2="{x}" y2="{center}"/>')
    svg.append(f'<rect class="terminal" x="{x}" y="140" width="140" height="72" rx="18"/>')
    svg.append('<text class="terminal-tag" x="' + str(x + 18) + '" y="163">终点</text>')
    svg.append(f'<text class="text" x="{x + 18}" y="187">任务目标</text>')
    if blockers or avoids:
        svg.append('<text class="zone-title" x="50" y="300">阻塞未知：不问清不开工</text>')
        for index, item in enumerate(blockers[:6]):
            svg.append(f'<text class="warn" x="50" y="{324 + index * 20}">· {escape(_text(item.get("text"), 46))}</text>')
        svg.append('<text class="zone-title" x="360" y="300">避让区：偏离即披露</text>')
        for index, item in enumerate(avoids[:6]):
            svg.append(f'<text class="warn" x="360" y="{324 + index * 20}">· {escape(_text(item.get("text"), 40))}</text>')
        if len(blockers) > 6 or len(avoids) > 6:
            svg.append('<text class="warn" x="50" y="410">下方只显示前 6 条；完整清单仍在 portrait / task anchors。</text>')
    svg.append('</svg>')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(svg), encoding="utf-8")
    return out
