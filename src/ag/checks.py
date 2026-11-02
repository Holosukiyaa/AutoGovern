"""Select and bind checks from the current ticket's actual worktree."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def selection(worktree: Path, enrolled: list[str]) -> dict[str, Any]:
    commands = []
    if enrolled and not any(".ag-check/" in str(argument).replace("\\", "/") for argument in enrolled):
        commands.append(list(enrolled))
    files = sorted(path for path in (worktree / ".ag-check").glob("check_*.py") if path.is_file())
    commands.extend([[sys.executable, "-X", "utf8", str(path.relative_to(worktree)).replace("\\", "/")] for path in files])
    evidence_files = sorted(path for path in (worktree / ".ag-check").rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"})
    hashes = {str(path.relative_to(worktree)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest() for path in evidence_files}
    signature = hashlib.sha256(json.dumps({"commands": commands, "files": hashes}, sort_keys=True).encode("utf-8")).hexdigest()
    return {"commands": commands, "files": hashes, "sha256": signature}


def run(worktree: Path, chosen: dict[str, Any]) -> dict[str, Any]:
    commands = chosen["commands"]
    outputs = []
    errors = []
    exits = []
    environment = os.environ.copy()
    if (worktree / "src" / "ag" / "__init__.py").is_file():
        environment["PYTHONPATH"] = str(worktree / "src") + os.pathsep + environment.get("PYTHONPATH", "")
    for command in commands:
        try:
            completed = subprocess.run(command, cwd=str(worktree), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, env=environment)
            exits.append(completed.returncode)
            outputs.append(completed.stdout or "")
            errors.append(completed.stderr or "")
        except OSError as exc:
            exits.append(1)
            errors.append(str(exc))
    return {"exit": next((code for code in exits if code), 0), "stdout": "\n".join(outputs)[-4000:], "stderr": "\n".join(errors)[-4000:], "undeclared": not commands, "check_argv": commands, "check_selection": chosen}
