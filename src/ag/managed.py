"""Enrolled projects. Identity is realpath so a junction is one checkout."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

SCHEMA = "ag.managed.v1"


class ChainBroken(Exception):
    """A physical check did not produce the expected result."""


def ag_home() -> Path:
    override = os.environ.get("AG_HOME")
    if override:
        return Path(override)
    return Path.home() / ".ag"


def managed_path() -> Path:
    return ag_home() / "managed.json"


def real_root(root: Path) -> Path:
    return Path(os.path.realpath(root.expanduser()))


def project_key(root: Path) -> str:
    real = real_root(root)
    digest = hashlib.sha256(str(real).replace("\\", "/").casefold().encode("utf-8")).hexdigest()[:12]
    name = re.sub(r"[^a-z0-9]+", "-", real.name.casefold()).strip("-") or "repo"
    return f"{name}-{digest}"


def lookup_project(root: Path) -> dict[str, Any] | None:
    wanted = str(real_root(root))
    for item in load_managed()["projects"]:
        if not isinstance(item, dict):
            continue
        stored = str(item.get("real") or item.get("root") or "")
        if stored and str(real_root(Path(stored))) == wanted:
            return item
    return None


def load_managed() -> dict[str, Any]:
    path = managed_path()
    if not path.is_file():
        return {"schema": SCHEMA, "projects": []}
    blob = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(blob, dict):
        raise ChainBroken("managed file is not an object")
    projects = blob.get("projects")
    if not isinstance(projects, list):
        projects = []
    return {"schema": SCHEMA, "projects": projects}


def save_managed(blob: dict[str, Any]) -> Path:
    path = managed_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
