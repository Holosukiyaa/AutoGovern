"""Short anchor template, plus the full skill after the first look."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .managed import ChainBroken


def _skill_dir() -> Path:
    repo = Path(__file__).resolve().parents[2] / "skills" / "ag-anchor"
    if (repo / "SKILL.md").is_file() and (repo / "brief.json").is_file():
        return repo
    installed = Path(sys.prefix) / "share" / "ag" / "skills" / "ag-anchor"
    if (installed / "SKILL.md").is_file() and (installed / "brief.json").is_file():
        return installed
    raise ChainBroken(f"ag-anchor skill is missing: {repo}")


def load_brief() -> dict[str, list[str]]:
    blob = json.loads((_skill_dir() / "brief.json").read_text(encoding="utf-8-sig"))
    if not isinstance(blob, dict):
        raise ChainBroken("anchor brief is not an object")
    out: dict[str, list[str]] = {}
    for key in ("write", "wait"):
        rows = blob.get(key)
        if not isinstance(rows, list) or not rows:
            raise ChainBroken(f"anchor brief missing {key}")
        out[key] = [str(item).strip() for item in rows if str(item).strip()]
    return out


def load_skill() -> str:
    text = (_skill_dir() / "SKILL.md").read_text(encoding="utf-8-sig").strip()
    if not text:
        raise ChainBroken("ag-anchor skill is empty")
    return text + "\n"


def anchor_guidance(template_issued: bool) -> dict[str, object]:
    """First look is the template. Every later look while unconfirmed is the full skill."""
    if not template_issued:
        return {"anchor_brief": load_brief()}
    return {"skill": load_skill()}
