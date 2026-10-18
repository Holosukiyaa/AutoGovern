"""Version-control a project's AG_HOME state dir so conclusions survive accidents.

Tracks conclusions and config (config.json, knowledge/, tickets, redlines, probes,
*-last.json). Never tracks churn (usage.jsonl, *-live.jsonl, reviews/, seat event
jsonl) — those are rolling logs governed by the anti-bloat gate, not history.

Commits after finish/abandon. Any git failure writes one audit line; it NEVER blocks
delivery — this is a recall floor, not a delivery gate.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .managed import real_root
from .store import append_project_jsonl, project_dir

# Churn that must stay out of version history.
_GITIGNORE = """# ag state dir: track conclusions+config, not rolling logs
usage.jsonl
*-live.jsonl
reviews/
ticket.jsonl
critic.jsonl
switch.jsonl
cleanup-audit.jsonl
probe-audit.jsonl
approvals.jsonl
migration.jsonl
*.bak
*.bak-*
"""


def _git(dirpath: Path, *args: str) -> tuple[int, str]:
    p = subprocess.run(
        ["git", "-C", str(dirpath), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def _audit(root: Path, action: str, detail: str) -> None:
    try:
        append_project_jsonl(real_root(root), "cleanup-audit.jsonl", {"action": action, "detail": detail})
    except Exception:
        import sys

        sys.stderr.write(f"ag: state-git audit write failed for {action}; not logged\n")


def ensure_state_repo(root: Path) -> bool:
    """git init the project state dir + write .gitignore. Idempotent; reuses existing .git."""
    base = project_dir(real_root(root))
    if not base.is_dir():
        return False
    try:
        if not (base / ".git").is_dir():
            rc, out = _git(base, "init")
            if rc != 0:
                _audit(root, "state-commit-failed", f"git init: {out[:120]}")
                return False
        ignore = base / ".gitignore"
        if not ignore.is_file():
            ignore.write_text(_GITIGNORE, encoding="utf-8")
        return True
    except Exception as exc:
        _audit(root, "state-commit-failed", f"init exc: {exc.__class__.__name__}")
        return False


def commit_state(root: Path, message: str) -> dict[str, Any]:
    """Commit tracked conclusions/config after a ticket settles. Never raises, never blocks.

    Skips when there is nothing to commit (idempotent — no empty commits)."""
    repo = real_root(root)
    base = project_dir(repo)
    if not ensure_state_repo(repo):
        return {"committed": False, "reason": "init-failed"}
    try:
        _git(base, "add", "-A")
        rc, out = _git(base, "diff", "--cached", "--quiet")
        if rc == 0:
            return {"committed": False, "reason": "no-change"}
        rc, out = _git(base, "-c", "user.name=ag", "-c", "user.email=ag@local", "commit", "-m", message)
        if rc != 0:
            _audit(repo, "state-commit-failed", f"commit: {out[:120]}")
            return {"committed": False, "reason": out[:120]}
        return {"committed": True, "message": message}
    except Exception as exc:
        _audit(repo, "state-commit-failed", f"commit exc: {exc.__class__.__name__}")
        return {"committed": False, "reason": exc.__class__.__name__}