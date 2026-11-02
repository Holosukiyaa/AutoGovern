"""Install the bundled ag skills (ag-anchor, ag-guide, ag-config, ag-troubleshooting)."""
from __future__ import annotations

import shutil
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

SKILL_NAMES: tuple[str, ...] = (
    "ag-anchor",
    "ag-guide",
    "ag-config",
    "ag-troubleshooting",
)

_SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"
_WHEEL_SKILLS_ROOT = Path(sys.prefix) / "share" / "ag" / "skills"


def _resolve_skills_root() -> Path:
    if (_SKILLS_ROOT / "ag-anchor").is_dir():
        return _SKILLS_ROOT
    return _WHEEL_SKILLS_ROOT


def bundled_skills() -> list[dict[str, str]]:
    root = _resolve_skills_root()
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for name in SKILL_NAMES:
        skill_md = root / name / "SKILL.md"
        out.append({"name": name, "path": str(skill_md)})
        seen.add(name)
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if child.is_dir() and child.name not in seen and (child / "SKILL.md").is_file():
                out.append({"name": child.name, "path": str(child / "SKILL.md")})
                seen.add(child.name)
    return out


def install_skill(target: str) -> str:
    skills_root = _resolve_skills_root()
    if not skills_root.is_dir():
        raise FileNotFoundError(f"bundled skills missing: {_SKILLS_ROOT} or {_WHEEL_SKILLS_ROOT}")
    home = Path.home()
    if target == "codex":
        base_dest = home / ".codex" / "skills"
    elif target == "grok":
        base_dest = home / ".grok" / "skills"
    else:
        raise ValueError(f"unknown skill target: {target}")
    base_dest.mkdir(parents=True, exist_ok=True)
    names: list[str] = list(SKILL_NAMES)
    for child in sorted(skills_root.iterdir()):
        if child.is_dir() and child.name not in names and (child / "SKILL.md").is_file():
            names.append(child.name)
    installed: list[str] = []
    for name in names:
        source = skills_root / name
        if not source.is_dir() or not (source / "SKILL.md").is_file():
            raise FileNotFoundError(f"bundled skill missing: {source / 'SKILL.md'}")
        dest = base_dest / name
        temporary = base_dest / f".{name}.install-{uuid.uuid4().hex}"
        shutil.copytree(source, temporary)
        backup = None
        if dest.exists():
            backup = dest.with_name(dest.name + ".bak")
            if backup.exists():
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                backup = dest.with_name(dest.name + f".bak-{stamp}-{uuid.uuid4().hex[:6]}")
            os.replace(dest, backup)
        try:
            os.replace(temporary, dest)
        except OSError:
            if backup is not None and not dest.exists():
                os.replace(backup, dest)
            raise
        installed.append(str(dest.resolve()))
    return "\n".join(installed)
