"""Reverse-dev checkup: find fat/glue and insert probes. Suggestions are not trust."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .queue import ChainBroken, add_exists, add_hash, load_queue

SOFTCAP = 800
SKIP_PARTS = {".git", "node_modules", "__pycache__", ".venv", "dist", ".ag"}


def _skip(path: Path) -> bool:
    return any(part in SKIP_PARTS for part in path.parts)


def _already(root: Path, kind: str, rel: str) -> bool:
    for item in load_queue(root).get("items") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "") == kind and str(item.get("path") or "").replace("\\", "/") == rel:
            return True
    return False


def _plant(root: Path, rel: str, *, note: str) -> list[dict[str, Any]]:
    planted: list[dict[str, Any]] = []
    if not _already(root, "exists", rel):
        try:
            planted.append(add_exists(root, rel, note=note))
        except ChainBroken:
            pass
    target = root / rel
    if target.is_file() and not _already(root, "hash", rel):
        try:
            planted.append(add_hash(root, rel, note=note))
        except ChainBroken:
            pass
    return planted


def checkup(root: Path, *, insert: bool = True) -> dict[str, Any]:
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
    inserted: list[dict[str, Any]] = []
    if insert:
        for hint in suggestions:
            rel = str(hint.get("path") or "")
            if not rel:
                continue
            note = f"auto from reverse-dev {hint.get('kind')}"
            inserted.extend(_plant(root, rel, note=note))
    return {
        "schema": "ag.checkup.v1",
        "root": str(root),
        "reminder": "checkup plants probes on fat/glue paths; it does not raise trust by itself",
        "suggestions": suggestions,
        "inserted": [{"id": item.get("id"), "kind": item.get("kind"), "path": item.get("path")} for item in inserted],
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
