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

# Judged chart positions (help 0-10, side-effect 0-10). Display only; may drift from code.
# color: green=该类该用 yellow=建议/体检 blue=看见不当门 red=该类更伤
CHART: dict[tuple[str, int], tuple[float, float, str]] = {
    ("ship", 1): (8.6, 2.8, "green"),
    ("ship", 2): (8.0, 3.6, "green"),
    ("ship", 3): (6.6, 4.0, "green"),
    ("ship", 4): (6.3, 4.6, "green"),
    ("ship", 5): (7.4, 4.4, "green"),
    ("ship", 6): (8.4, 3.2, "green"),
    ("ship", 7): (7.6, 5.0, "green"),
    ("ship", 8): (7.0, 4.8, "green"),
    ("ship", 9): (5.6, 3.8, "green"),
    ("ship", 10): (5.2, 4.4, "green"),
    ("ship", 11): (5.4, 5.2, "green"),
    ("heal", 1): (6.6, 4.2, "yellow"),
    ("heal", 2): (7.0, 3.4, "yellow"),
    ("heal", 3): (5.8, 3.0, "yellow"),
    ("heal", 4): (7.6, 3.2, "green"),
    ("lift", 1): (6.4, 2.4, "green"),
    ("lift", 2): (6.8, 3.2, "yellow"),
    ("lift", 3): (7.4, 4.0, "yellow"),
    ("lift", 4): (8.0, 5.2, "yellow"),
    ("lift", 5): (5.8, 3.0, "yellow"),
    ("lift", 6): (6.2, 3.6, "yellow"),
    ("lift", 7): (5.4, 2.8, "yellow"),
    ("lift", 8): (6.6, 2.6, "yellow"),
    ("lift", 9): (7.0, 3.8, "yellow"),
    ("lift", 10): (5.6, 3.4, "yellow"),
    ("lift", 11): (8.2, 5.6, "yellow"),
    ("see", 1): (7.2, 2.4, "blue"),
    ("see", 2): (6.8, 2.8, "blue"),
    ("see", 3): (7.6, 2.2, "blue"),
    ("see", 4): (6.4, 3.0, "blue"),
    ("see", 5): (8.2, 2.6, "green"),
    ("see", 6): (7.8, 3.2, "blue"),
    ("see", 7): (6.0, 2.6, "blue"),
    ("see", 8): (6.6, 3.4, "blue"),
    ("see", 9): (7.0, 2.0, "blue"),
}

INK = {"green": "#3dbe8c", "yellow": "#e0b34a", "blue": "#6ea8ff", "red": "#e05b6a"}

# Poster order: 交货 / 治病 / 抬正确率 / 看见
DIMS = (
    ("ship", "交货 · 防事故", "主仓不是工地。流程完成 ≠ 产品过关。只有这些能签发 product、拒绝 finish。探针绑 ship-序号。"),
    ("heal", "治病 · 仓库已经病了", "药方针对叠门（典型：CF 工作台 CSS 00→103 盖皮）。不跟着交货自动启用，先看见抢门再治。不能挡交货。探针绑 heal-序号。"),
    ("lift", "抬正确率 · 这一笔写得对", "建议和清单，不能挡交货。探针绑 lift-序号。"),
    ("see", "看见 / 组织", "天气预报，不是警察局。探针绑 see-序号。"),
)


def _esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=True)


def _landed(item: dict[str, Any]) -> bool:
    if not item.get("live"):
        return False
    lane = str(item.get("lane") or "")
    seq = int(item["seq"])
    if lane == "ship":
        return True
    from .advice import HANDLERS

    return (lane, seq) in HANDLERS


def _xy(help_n: float, side: float, w: int, h: int) -> tuple[float, float]:
    pad_l, pad_b, pad_r, pad_t = 40, 26, 10, 10
    x = pad_l + max(0.0, min(10.0, help_n)) / 10.0 * (w - pad_l - pad_r)
    y = pad_t + (1.0 - max(0.0, min(10.0, side)) / 10.0) * (h - pad_t - pad_b)
    return x, y


def _scatter(lane: str, items: list[dict[str, Any]], *, w: int = 340, h: int = 220) -> str:
    pad_l, pad_b, pad_r, pad_t = 40, 26, 10, 10
    x0, y0 = _xy(0, 0, w, h)
    x1, y1 = _xy(10, 10, w, h)
    parts = [
        f"<svg class='chart' viewBox='0 0 {w} {h}' width='100%' role='img' "
        f"aria-label='{_esc(lane)} 坐标图'>",
        f"<rect x='0' y='0' width='{w}' height='{h}' fill='#0e1218' rx='8'/>",
        f"<line x1='{pad_l}' y1='{h - pad_b}' x2='{w - pad_r}' y2='{h - pad_b}' stroke='#2a3442' />",
        f"<line x1='{pad_l}' y1='{pad_t}' x2='{pad_l}' y2='{h - pad_b}' stroke='#2a3442' />",
        f"<line x1='{x0:.1f}' y1='{y0:.1f}' x2='{x1:.1f}' y2='{y1:.1f}' "
        "stroke='#3a4656' stroke-dasharray='4 4' />",
        f"<text x='{w / 2:.0f}' y='{h - 6}' text-anchor='middle' fill='#8b97a8' font-size='10'>真实帮助 →</text>",
        f"<text x='{pad_l}' y='{pad_t + 9}' fill='#8b97a8' font-size='10'>副作用 ↑</text>",
    ]
    for item in items:
        if not _landed(item):
            continue
        seq = int(item["seq"])
        help_n, side, color = CHART.get((lane, seq), (1.0 + seq * 0.7, 1.5, "blue"))
        cx, cy = _xy(help_n, side, w, h)
        fill = INK.get(color, INK["blue"])
        name = str(item.get("name") or "")
        parts.append(
            f"<a href='#{lane}-{seq}'>"
            f"<circle cx='{cx:.1f}' cy='{cy:.1f}' r='9' fill='{fill}' />"
            f"<text x='{cx:.1f}' y='{cy + 3.5:.1f}' text-anchor='middle' fill='#0e1218' "
            f"font-size='9' font-weight='700'>{seq}</text>"
            f"<title>{_esc(f'{lane}-{seq} {name} · 已落地')}</title>"
            "</a>"
        )
    parts.append("</svg>")
    return "".join(parts)


def _landed_strip(lane: str, items: list[dict[str, Any]]) -> str:
    bits = []
    for item in items:
        if not _landed(item):
            continue
        seq = int(item["seq"])
        bits.append(f"<a href='#{lane}-{seq}'>{seq}. {_esc(item.get('name'))}</a>")
    if not bits:
        return "<p class='muted'>这一维还没有落地策略。</p>"
    return f"<nav class='toc landed'>已落地 {len(bits)}　" + "　".join(bits) + "</nav>"


def _maps() -> str:
    cells = []
    for lane, title, blurb in DIMS:
        items = list_lane(lane)
        n = sum(1 for item in items if _landed(item))
        cells.append(
            f"<div class='map-cell'>"
            f"<h3><a href='#dim-{lane}'>{_esc(title)}</a> <span class='tag'>{n} 已落地</span></h3>"
            f"<p>{_esc(blurb)}</p>"
            f"{_scatter(lane, items)}"
            f"{_landed_strip(lane, items)}"
            "</div>"
        )
    return (
        "<section class='maps-wrap'>"
        "<h2>策略图 · 四维坐标</h2>"
        "<p>横轴真实帮助，纵轴副作用，虚线右下 = 正面大于负面。点的位置是判断，不是 usage 算分；"
        "以后可能和代码不同步。只画已经落地的策略。绿=该类该用　黄=建议/体检　蓝=看见，不当门。</p>"
        "<div class='maps'>" + "".join(cells) + "</div>"
        "</section>"
    )


def _strategy_card(item: dict[str, Any], *, landed: bool, index: int, lane: str) -> str:
    plug = "可拔" if item.get("pluggable") else "内核"
    state = "已落地" if landed else "未落地"
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
        mark = "已落地" if _landed(item) else "未落地"
        links.append(f"<a href='#{lane}-{seq}'>{seq}. {_esc(item.get('name'))} · {mark}</a>")
    return "<nav class='toc'>" + "　".join(links) + "</nav>"


def _lane_block(title: str, blurb: str, items: list[dict[str, Any]], *, lane: str) -> str:
    n = sum(1 for item in items if _landed(item))
    cards = "".join(
        _strategy_card(item, landed=_landed(item), index=int(item["seq"]), lane=lane)
        for item in items
    )
    opened = " open" if lane == "ship" else ""
    return (
        f"<details class='dim' id='dim-{_esc(lane)}'{opened}>"
        f"<summary>{_esc(title)}（{n} 已落地 / {len(items)}）</summary>"
        f"<p>{_esc(blurb)}</p>"
        f"{_scatter(lane, items, w=520, h=280)}"
        f"{_toc(list(items), lane)}"
        f"{cards}</details>"
    )


def _lane_cards() -> str:
    return "".join(
        _lane_block(title, blurb, list_lane(lane), lane=lane) for lane, title, blurb in DIMS
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


def _css() -> str:
    return """
  body { margin:0; background:#0e1218; color:#e8eef6; font-family:"Microsoft YaHei","Segoe UI",sans-serif; }
  main { max-width:1100px; margin:0 auto; padding:28px 24px 48px; }
  h1 { font-size:22px; margin:0 0 6px; }
  .sub { color:#8b97a8; font-size:13px; line-height:1.55; margin-bottom:22px; }
  section, details.dim { background:#141b24; border:1px solid rgba(255,255,255,.08); border-radius:12px; padding:14px 16px 8px; margin-bottom:14px; }
  h2 { font-size:16px; margin:0 0 8px; }
  h3 { font-size:14px; margin:0 0 6px; }
  p, p.muted { color:#8b97a8; font-size:13px; margin:0 0 12px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { text-align:left; padding:6px 8px; border-bottom:1px solid rgba(255,255,255,.06); vertical-align:top; }
  th { color:#9eabbc; font-weight:600; }
  td.num { width:48px; }
  td.bar { width:120px; }
  .bar { display:flex; height:8px; background:#1c2430; border-radius:99px; overflow:hidden; }
  .help { background:#3dbe8c; display:block; height:8px; }
  .block { background:#e05b6a; display:block; height:8px; }
  .strat { border-top:1px solid rgba(255,255,255,.06); padding:12px 0 10px; }
  .strat h3 { font-size:14px; margin:0 0 8px; }
  .idx { color:#6ea8ff; margin-right:4px; }
  .tag { color:#9eabbc; font-size:12px; font-weight:400; }
  .toc { font-size:12px; line-height:1.7; margin:0 0 12px; color:#9eabbc; }
  .toc a { color:#6ea8ff; text-decoration:none; }
  .toc a:hover { text-decoration:underline; }
  dl { margin:0; }
  dt { color:#6ea8ff; font-size:12px; margin-top:6px; }
  dd { margin:2px 0 0; font-size:13px; line-height:1.55; color:#e8eef6; }
  .maps { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
  .map-cell { background:#0e1218; border-radius:10px; padding:10px 10px 4px; }
  .map-cell h3 a { color:#e8eef6; text-decoration:none; }
  .map-cell h3 a:hover { color:#6ea8ff; }
  .chart { display:block; margin:0 0 8px; }
  details.dim > summary { cursor:pointer; font-size:16px; font-weight:600; margin:0 0 10px; }
  details.dim > summary::-webkit-details-marker { color:#6ea8ff; }
  @media (max-width: 800px) { .maps { grid-template-columns:1fr; } }
"""


def _script() -> str:
    return """
<script>
(function () {
  function openTarget(id) {
    var el = document.getElementById(id);
    if (!el) return;
    var dim = el.closest("details") || (el.tagName === "DETAILS" ? el : null);
    if (dim) dim.open = true;
  }
  document.addEventListener("click", function (e) {
    var a = e.target.closest("a[href^='#']");
    if (!a) return;
    openTarget(a.getAttribute("href").slice(1));
  });
  if (location.hash) openTarget(location.hash.slice(1));
})();
</script>
"""


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
{_css()}
</style>
</head>
<body>
<main>
<h1>ag 看板</h1>
<p class="sub">只读展示。关掉这个文件不影响交货。核心是 git、测试和 ~/.ag 里的账。网页不是第四维。坐标图只用来看清楚已经落地的策略，折叠维度即可。</p>
{usage_html}
{_maps()}
{_lane_cards()}
</main>
{_script()}
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
