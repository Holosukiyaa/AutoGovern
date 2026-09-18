"""Read-only bit on tracked canonical files while a task is open."""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


def _tracked_files(root: Path) -> list[Path]:
    ran = subprocess.run(
        ["git", "-C", str(root), "ls-files"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    out: list[Path] = []
    for line in (ran.stdout or "").splitlines():
        rel = line.strip().strip('"')
        if not rel:
            continue
        path = root / rel.replace("/", os.sep)
        if not path.is_file():
            continue
        if ".git" in set(path.resolve().parts):
            continue
        out.append(path)
    return out


def freeze_canonical(root: Path) -> None:
    """Make tracked canonical files read-only. Does not touch .git, worktree, or AG_HOME."""
    root = Path(root)
    for path in _tracked_files(root):
        try:
            path.chmod(path.stat().st_mode & ~stat.S_IWRITE)
        except OSError:
            continue


def thaw_canonical(root: Path) -> None:
    """Restore user-write on tracked canonical files."""
    root = Path(root)
    for path in _tracked_files(root):
        try:
            path.chmod(path.stat().st_mode | stat.S_IWRITE)
        except OSError:
            continue
