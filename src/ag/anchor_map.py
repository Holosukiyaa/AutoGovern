"""Unicode intent-anchor maps. No SVG."""
from __future__ import annotations

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
