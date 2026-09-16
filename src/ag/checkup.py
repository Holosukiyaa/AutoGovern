"""Temporary reverse-dev checkup. Suggestions, not verification."""
from __future__ import annotations

from pathlib import Path
from typing import Any

SOFTCAP = 800
SKIP_PARTS = {".git", "node_modules", "__pycache__", ".venv", "dist", ".ag"}


def _skip(path: Path) -> bool:
    return any(part in SKIP_PARTS for part in path.parts)


def checkup(root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    suggestions: list[dict[str, Any]] = []
    for path in root.rglob("*.py"):
        if _skip(path):
            continue
        try:
            lines = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue
        if lines < SOFTCAP:
            continue
        rel = path.relative_to(root).as_posix()
        suggestions.append(
            {
                "kind": "fat",
                "path": rel,
                "lines": lines,
                "speech": "wide",
                "claim": f"{rel} has {lines} lines; may slow AI reuse. Not a trust fence.",
            }
        )
    glue = _glue_suggestions(root)
    suggestions.extend(glue)
    return {
        "schema": "ag.checkup.v1",
        "root": str(root),
        "reminder": "checkup is reverse-dev advice for unverified or gluey areas; it does not raise trust_rate",
        "suggestions": suggestions,
    }


def _glue_suggestions(root: Path) -> list[dict[str, Any]]:
    try:
        from ag2c.flatten import flatten_glue_scan
    except ImportError:
        return []
    try:
        scan = flatten_glue_scan(root, under=".")
    except Exception:
        return []
    out = []
    for item in scan.get("items") or []:
        if not isinstance(item, dict) or not item.get("glue"):
            continue
        rel = str(item.get("file") or "")
        names = item.get("names") or []
        out.append(
            {
                "kind": "glue",
                "path": rel,
                "names": names,
                "speech": "broad",
                "claim": f"{rel} still reexports {', '.join(str(n) for n in names)}; AI reuse tax. Not a trust fence.",
            }
        )
    return out
