"""T10: sealed target graduation, ticket-only retirement and guard cost."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from .history import read_records
from .managed import ChainBroken, project_key, real_root
from .workspace import _canonical_root, load_task

_retiring = ContextVar("ag_retiring_guards", default=("", ()))


def validate(root, spec, folder):
    """r1/r4: validate declarations before creating a worktree or pending seal."""
    from .ticket_package import _invalid, _relative, _text, sealed_dir
    from .probe import _load, store_path

    graduates = spec.get("graduate", [])
    if not isinstance(graduates, list):
        _invalid("graduate", "expected list")
    finished = {row["task_id"] for row in read_records(root, kind="task-step")
                if row["payload"].get("phase") == "finish"} if graduates else set()
    for index, entry in enumerate(graduates):
        field = f"graduate[{index}]"
        if not isinstance(entry, dict):
            _invalid(field, "expected object")
        source, source_spec = folder, spec
        if "task" in entry:
            task_id = _text(entry["task"], field + ".task")
            if task_id not in finished:
                _invalid(field + ".task", "source ticket must be merged")
            try:
                source = sealed_dir(root, task_id)
                source_spec = json.loads((source / "spec.json").read_text(encoding="utf-8"))
            except (OSError, ValueError, ChainBroken):
                _invalid(field + ".task", "source package unavailable")
        rel = _relative(entry.get("file"), field + ".file")
        target = source / rel
        if (not target.is_file() or not target.resolve().is_relative_to((source / "checks").resolve())
                or not any(row.get("file") == str(rel) and row.get("kind") == "target" for row in source_spec.get("checks", []))):
            _invalid(field + ".file", "expected a sealed target check")
        if "area" in entry:
            if not isinstance(entry["area"], list) or not entry["area"]:
                _invalid(field + ".area", "expected nonempty relative patterns")
            for pattern in entry["area"]:
                _relative(pattern, field + ".area")
    retires = spec.get("retires", [])
    if not isinstance(retires, list):
        _invalid("retires", "expected list")
    existing = {row.get("id") for row in _load(store_path(root))["probes"] if row.get("origin") == "graduated"} if retires else set()
    for index, entry in enumerate(retires):
        field = f"retires[{index}]"
        if not isinstance(entry, dict):
            _invalid(field, "expected object")
        identity = _text(entry.get("id"), field + ".id")
        if identity not in existing:
            _invalid(field + ".id", "expected an existing graduated guard")
        _text(entry.get("reason"), field + ".reason", 20)


def guard_row(root, task, entry):
    """r2/r3: derive the stable guard identity and source area without copying checks."""
    from .ticket_package import sealed_dir

    source = entry.get("task", task["id"])
    spec = task["package_spec"] if source == task["id"] else json.loads((sealed_dir(root, source) / "spec.json").read_text(encoding="utf-8"))
    return {"id": f"grad-{source}-{Path(entry['file']).stem}"[:64], "origin": "graduated", "state": "armed",
            "area": entry.get("area", spec["scope"]["allow"]), "graduated_by": task["id"],
            "graduated_at": datetime.now(timezone.utc).isoformat(),
            "observation": {"kind": "sealed_check", "task": source, "file": entry["file"], "timeout_s": 300}}


def complete(root, task):
    """r2/r4: apply only after a successful merge; retries skip already installed ids."""
    from .probe import _load, _save, store_path, audit_note

    path = store_path(root)
    spec = task.get("package_spec", {})
    if not spec.get("graduate") and not spec.get("retires"):
        return
    blob = _load(path)
    for entry in spec.get("retires", []):
        target = next((row for row in blob["probes"] if row.get("id") == entry["id"] and row.get("origin") == "graduated"), None)
        if target is not None:
            blob["probes"].remove(target)
            _save(path, blob)
            audit_note(root, action="drop", probe_id=entry["id"], area=target.get("area"), reason=entry["reason"], by=f"ticket:{task['id']}")
    for entry in spec.get("graduate", []):
        row = guard_row(root, task, entry)
        if any(existing.get("id") == row["id"] for existing in blob["probes"]):
            continue
        blob["probes"].append(row)
        _save(path, blob)
        audit_note(root, action="graduate", probe_id=row["id"], area=row["area"], by=f"ticket:{task['id']}")


def verification_scope(function):
    """r4: retirement skips apply to all evaluations within this verify, not later calls."""
    @wraps(function)
    def call(root, *args, **kwargs):
        key = project_key(real_root(root))
        task = load_task(key) or {}
        ids = tuple(entry["id"] for entry in task.get("package_spec", {}).get("retires", []))
        token = _retiring.set((key, ids))
        try:
            return function(root, *args, **kwargs)
        finally:
            _retiring.reset(token)
    return call


def retired_ids(root):
    """r4: project-bound ids for the current verify only."""
    key, ids = _retiring.get()
    return ids if key == project_key(real_root(root)) else ()


def backfills(root, task):
    """r3: earlier targets must run now, even when their area was not touched."""
    return [guard_row(root, task, entry) for entry in task.get("package_spec", {}).get("graduate", []) if "task" in entry]


def run_sealed(tree, observation):
    """r3: verify all sealed check hashes before executing the original script."""
    from .ticket_package import sealed_dir, file_hashes, _relative
    from .probe import _tail

    try:
        folder = sealed_dir(_canonical_root(tree), observation["task"])
        seal = json.loads((folder / "seal.json").read_text(encoding="utf-8"))
        expected = {name.removeprefix("checks/"): value for name, value in seal["files"].items()
                    if name.startswith("checks/") and "__pycache__" not in Path(name).parts}
        actual = {name.removeprefix("checks/"): value for name, value in file_hashes(folder, ignore_pycache=True).items() if name.startswith("checks/")}
        rel = _relative(observation["file"], "sealed_check.file")
        if not str(rel).startswith("checks/") or str(rel).removeprefix("checks/") not in expected or actual != expected:
            raise ValueError("sealed checks differ")
        script = folder / rel
        if not script.is_file() or not script.resolve().is_relative_to((folder / "checks").resolve()):
            raise ValueError("check missing or outside package")
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ChainBroken) as exc:
        return "red", 1, f"guard-tampered: {exc}"
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if (tree / "src").is_dir():
        env["PYTHONPATH"] = str(tree / "src") + os.pathsep + str(tree)
    try:
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(script)], cwd=tree, env=env,
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    except subprocess.TimeoutExpired:
        return "red", -1, "sealed_check timeout after 300s"
    except OSError as exc:
        return "red", -1, str(exc)
    return ("green" if result.returncode == 0 else "red"), result.returncode, _tail(result.stdout + "\n" + result.stderr)


def cost(root):
    """r5: latest graduated-guard runtime only; no hazards or next-action changes."""
    from .probe import _load, store_path

    rows = [row for row in _load(store_path(root))["probes"] if row.get("origin") == "graduated"]
    seconds = sum(float(row.get("last_seconds") or 0) for row in rows)
    return {"count": len(rows), "seconds": seconds, "threshold": 600, "due": seconds >= 600,
            "message": "毕业守护耗时达到 600 秒；可开票用 retires 精简。" if seconds >= 600 else ""}
