"""Read-only HTML dashboard. Not a lane. Not the core."""
from __future__ import annotations

import html
import webbrowser
from pathlib import Path
from typing import Any

from .catalog import list_lane
from . import see
from .managed import ag_home

TOOLS = [
    {
        "name": "ag_gui",
        "description": "Write a read-only HTML dashboard and return its path. Display only.",
        "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}}},
    },
]


def _esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=True)


def _strategy_card(item: dict[str, Any], *, live: bool, index: int, lane: str) -> str:
    plug = "可拔" if item.get("pluggable") else "内核"
    state = "在跑" if live else "未做"
    anchor = f"{lane}-{index}"
    return (
        f"<article class='strat' id='{_esc(anchor)}'>"
        f"<h3><span class='idx'>{index}.</span> {_esc(item.get('name'))} "
        f"<span class='tag'>{plug} · {state}</span></h3>"
        "<dl>"
        f"<dt>参考什么故事</dt><dd>{_esc(item.get('story'))}</dd>"
        f"<dt>这个策略怎么做</dt><dd>{_esc(item.get('how'))}</dd>"
        f"<dt>预期能解决什么</dt><dd>{_esc(item.get('solves'))}</dd>"
        "</dl>"
        "</article>"
    )


def _toc(items: list[dict[str, Any]], lane: str) -> str:
    links = []
    for item in items:
        seq = int(item["seq"])
        links.append(f"<a href='#{lane}-{seq}'>{seq}. {_esc(item.get('name'))}</a>")
    return "<nav class='toc'>" + "　".join(links) + "</nav>"


def _lane_block(title: str, blurb: str, items: list[dict[str, Any]], *, lane: str) -> str:
    cards = "".join(
        _strategy_card(item, live=bool(item.get("live")), index=int(item["seq"]), lane=lane)
        for item in items
    )
    return (
        f"<section><h2>{_esc(title)}（{len(items)}）</h2>"
        f"<p>{_esc(blurb)}</p>"
        f"{_toc(list(items), lane)}"
        f"{cards}</section>"
    )


def _lane_cards() -> str:
    return "".join(
        [
            _lane_block(
                "交货 ship · 在跑",
                "主仓不是工地。只有这些能签发 product、拒绝 finish。探针绑 ship-序号。",
                list_lane("ship"),
                lane="ship",
            ),
            _lane_block(
                "抬正确率 lift · 未做",
                "建议和清单，不能挡交货。探针绑 lift-序号。",
                list_lane("lift"),
                lane="lift",
            ),
            _lane_block(
                "治病 heal · 未做",
                "建议和清单，不能挡交货。探针绑 heal-序号。",
                list_lane("heal"),
                lane="heal",
            ),
            _lane_block(
                "看见 see · 展示",
                "天气预报，不是警察局。探针绑 see-序号。",
                list_lane("see"),
                lane="see",
            ),
        ]
    )


def _usage_table(report: dict[str, Any]) -> str:
    rows = []
    for index, item in enumerate(report.get("items") or [], start=1):
        hits = int(item.get("hits") or 0)
        help_n = int(item.get("help") or 0)
        block_n = int(item.get("block") or 0)
        width = max(help_n + block_n, 1)
        rows.append(
            "<tr>"
            f"<td>{int(item.get('seq') or index)}. {_esc(item.get('name'))}</td>"
            f"<td class='num'>{help_n}</td>"
            f"<td class='num'>{block_n}</td>"
            f"<td class='bar'><span class='help' style='width:{100 * help_n / width:.0f}%'></span>"
            f"<span class='block' style='width:{100 * block_n / width:.0f}%'></span></td>"
            f"<td>{'从未用' if hits == 0 else ''}</td>"
            "</tr>"
        )
    never = ", ".join(_esc(x) for x in (report.get("never_used") or [])) or "无"
    return (
        f"<section><h2>这个仓的账 · {_esc(report.get('root'))}</h2>"
        "<p>help = 用上了，block = 拦住了。不是产品绿。</p>"
        "<table><thead><tr><th>项</th><th>help</th><th>block</th><th></th><th></th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        f"<p>从未用：{never}</p></section>"
    )


def render_dashboard(root: Path | None = None) -> str:
    usage_html = ""
    if root is not None and str(root).strip():
        usage_html = _usage_table(see.usage(Path(root)))
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>ag 看板 · 只读</title>
<style>
  body {{ margin:0; background:#0e1218; color:#e8eef6; font-family:"Microsoft YaHei","Segoe UI",sans-serif; }}
  main {{ max-width:1100px; margin:0 auto; padding:28px 24px 48px; }}
  h1 {{ font-size:22px; margin:0 0 6px; }}
  .sub {{ color:#8b97a8; font-size:13px; line-height:1.55; margin-bottom:22px; }}
  section {{ background:#141b24; border:1px solid rgba(255,255,255,.08); border-radius:12px; padding:14px 16px 8px; margin-bottom:14px; }}
  h2 {{ font-size:16px; margin:0 0 8px; }}
  p {{ color:#8b97a8; font-size:13px; margin:0 0 12px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid rgba(255,255,255,.06); vertical-align:top; }}
  th {{ color:#9eabbc; font-weight:600; }}
  td.num {{ width:48px; }}
  td.bar {{ width:120px; }}
  .bar {{ display:flex; height:8px; background:#1c2430; border-radius:99px; overflow:hidden; }}
  .help {{ background:#3dbe8c; display:block; height:8px; }}
  .block {{ background:#e05b6a; display:block; height:8px; }}
  .strat {{ border-top:1px solid rgba(255,255,255,.06); padding:12px 0 10px; }}
  .strat h3 {{ font-size:14px; margin:0 0 8px; }}
  .idx {{ color:#6ea8ff; margin-right:4px; }}
  .tag {{ color:#9eabbc; font-size:12px; font-weight:400; }}
  .toc {{ font-size:12px; line-height:1.7; margin:0 0 12px; color:#9eabbc; }}
  .toc a {{ color:#6ea8ff; text-decoration:none; }}
  .toc a:hover {{ text-decoration:underline; }}
  dl {{ margin:0; }}
  dt {{ color:#6ea8ff; font-size:12px; margin-top:6px; }}
  dd {{ margin:2px 0 0; font-size:13px; line-height:1.55; color:#e8eef6; }}
</style>
</head>
<body>
<main>
<h1>ag 看板</h1>
<p class="sub">只读展示。关掉这个文件不影响交货。核心是 git、测试和 ~/.ag 里的账。网页不是第四维。</p>
{usage_html}
{_lane_cards()}
</main>
</body>
</html>
"""


def write_dashboard(root: Path | None = None, *, browse: bool = False) -> Path:
    path = ag_home() / "dashboard.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_dashboard(root), encoding="utf-8")
    if browse:
        webbrowser.open(path.resolve().as_uri())
    return path


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    from .managed import ChainBroken

    if name == "ag_gui":
        raw = str(args.get("root") or "").strip()
        path = write_dashboard(Path(raw) if raw else None, browse=False)
        return {"schema": "ag.gui.v1", "path": str(path), "reminder": "HTML is a view, not a lane"}
    raise ChainBroken(f"gui has no tool {name}")
