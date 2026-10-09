"""Install the bundled ag-anchor skill."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

_SOURCE = Path(__file__).resolve().parents[2] / "skills" / "ag-anchor"
_WHEEL_SOURCE = Path(sys.prefix) / "share" / "ag" / "skills" / "ag-anchor"


def install_skill(target: str) -> str:
    source = _SOURCE if _SOURCE.is_dir() else _WHEEL_SOURCE
    if not source.is_dir():
        raise FileNotFoundError(f"bundled skill missing: {_SOURCE} or {_WHEEL_SOURCE}")
    home = Path.home()
    if target == "codex":
        dest = home / ".codex" / "skills" / "ag-anchor"
    elif target == "grok":
        dest = home / ".grok" / "skills" / "ag-anchor"
    else:
        raise ValueError(f"unknown skill target: {target}")
    if dest.exists():
        backup = dest.with_name(dest.name + ".bak")
        if backup.exists():
            shutil.rmtree(backup)
        shutil.copytree(dest, backup)
        shutil.rmtree(dest)
    shutil.copytree(source, dest)
    return str(dest.resolve())
