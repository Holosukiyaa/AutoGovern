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


def _split_body(line: str) -> tuple[str, str]:
    if ":" in line:
        prefix, body = line.split(":", 1)
        return prefix.strip(), body.strip()
    if "：" in line:
        prefix, body = line.split("：", 1)
        return prefix.strip(), body.strip()
    return "", ""


def resolve_fixed(portrait: str, explicit: list[str] | None = None) -> list[str]:
    """Locked done-state lines. Explicit lines win, then 固定/做成之后, then the portrait itself."""
    rows = [str(item).strip() for item in (explicit or []) if str(item).strip()]
    if rows:
        return rows
    parsed: list[str] = []
    for raw in str(portrait or "").splitlines():
        prefix, body = _split_body(raw.strip())
        if prefix in {"固定", "做成之后", "fixed"} and body:
            parsed.append(body)
    if parsed:
        return parsed
    kept: list[str] = []
    for raw in str(portrait or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        prefix, _body = _split_body(line)
        low = prefix.lower() if prefix else line.lower()
        if low.startswith("anchor") or low in {"guard", "default", "固定", "做成之后", "fixed"}:
            continue
        kept.append(line)
    text = "\n".join(kept).strip()
    return [text] if text else []


def hard_rules(anchors: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("text") or "").strip() for item in anchors if _kind(item) == "hard" and str(item.get("text") or "").strip()]


def attention_anchors(anchors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in anchors if _kind(item) in {"soft", "discoverable", "defaulted", "obsolete"}]


def default_artifact_path(title: str) -> Path:
    from subprocess import DEVNULL, check_output

    from .managed import ag_home, project_key, real_root

    root = real_root(Path(check_output(["git", "rev-parse", "--show-toplevel"], cwd=Path.cwd(), stderr=DEVNULL, text=True).strip()))
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in title).strip("-")
    return ag_home() / "worktrees" / project_key(root) / "anchor-maps" / f"{safe or 'anchor-map'}.txt"


def write_unicode(
    title: str,
    portrait: str,
    out: Path,
    *,
    anchors: list[dict[str, Any]] | None = None,
    current_anchor: str = "",
    guards: list[str] | None = None,
    defaults: list[str] | None = None,
    fixed: list[str] | None = None,
    fixed_rules: list[str] | None = None,
) -> Path:
    """Write one Unicode intent map. An .svg destination is stored as .txt."""
    if anchors is None:
        from .loop import parse_anchors

        anchors = parse_anchors(portrait)
    anchors = anchors or []
    if fixed is None:
        fixed = resolve_fixed(portrait, None)
    if fixed_rules is None:
        fixed_rules = hard_rules(anchors)
    destination = Path(out)
    if destination.suffix.lower() == ".svg":
        destination = destination.with_suffix(".txt")
    text = render_unicode(title, anchors, current_anchor, guards, defaults, fixed, fixed_rules)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    return destination


def render_unicode(
    title: str,
    anchors: list[dict[str, Any]],
    current_anchor: str = "",
    guards: list[str] | None = None,
    defaults: list[str] | None = None,
    fixed: list[str] | None = None,
    fixed_rules: list[str] | None = None,
) -> str:
    current_anchor = str(current_anchor or "").strip()
    symbols = {
        "soft": "◇",
        "discoverable": "?",
        "defaulted": "◇",
        "obsolete": "x",
    }
    locked = [str(item).strip() for item in (fixed or []) if str(item).strip()]
    rules = [str(item).strip() for item in (fixed_rules or []) if str(item).strip()]
    lines = [f"◆ {title}", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    if locked or rules:
        lines.append("■ 固定")
        lines.extend(f"  {item}" for item in locked)
        lines.extend(f"  {item}" for item in rules)
        lines.append("")
    lines.extend(["START", "  用户一句话", "  │"])
    route_anchors = attention_anchors(anchors)
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
    lines.extend(["  ▼", "● END", "  上面那段固定结果成立", ""])
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
    lines.extend(
        [
            "图例",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "■ 固定  做成之后的样子，确认前不改",
            "◇ 注意力  ? 还没看见  x 避开或已失效  ● 终点",
            "■ guards 独立验收规则  ◇ defaults 可协商默认",
        ]
    )
    return "\n".join(lines)
