"""Low-level workspace tools shared by commands and hooks (T9s r1)."""
from __future__ import annotations

import hmac
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .managed import ChainBroken, ag_home, project_key
from .store import replace_file

PREV_UNSET = "__unset__"
PREVIOUS_HOOK_TIMEOUT_S = 120


def git_run(cwd: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
    )


def git(cwd: Path, *args: str, check: bool = True, env: dict[str, str] | None = None) -> str:
    completed = git_run(cwd, *args, env=env)
    text = (completed.stdout or "").strip()
    if check and completed.returncode != 0:
        err = (completed.stderr or text or "git failed").strip()
        raise ChainBroken(err)
    return text


def _posix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_git_path(cwd: Path, raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = cwd / path
    return path.resolve()


def _is_canonical(root: Path) -> bool:
    git_dir = _resolve_git_path(root, git(root, "rev-parse", "--git-dir"))
    common = _resolve_git_path(root, git(root, "rev-parse", "--git-common-dir"))
    return git_dir == common


def _canonical_root(cwd: Path) -> Path:
    common = _resolve_git_path(cwd, git(cwd, "rev-parse", "--git-common-dir"))
    return common.parent if common.name == ".git" else common.parent


def _task_path(key: str) -> Path:
    return ag_home() / "projects" / key / "task.json"


def load_task(key: str) -> dict[str, Any] | None:
    path = _task_path(key)
    if not path.is_file():
        return None
    blob = json.loads(path.read_text(encoding="utf-8"))
    return blob if isinstance(blob, dict) else None


def save_task(key: str, task: dict[str, Any] | None) -> None:
    path = _task_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    if task is None:
        if path.is_file():
            path.unlink()
        return
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(task, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        replace_file(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def tree_digest(worktree: Path) -> str:
    if git(worktree, "ls-files", "--", ".ag-check"):
        raise ChainBroken("tracked-ticket-checks: keep .ag-check outside the product index")
    with tempfile.TemporaryDirectory(prefix="ag-tree-") as temporary:
        environment = os.environ.copy()
        environment["GIT_INDEX_FILE"] = str(Path(temporary) / "index")
        current_index = _resolve_git_path(worktree, git(worktree, "rev-parse", "--git-path", "index"))
        if current_index.is_file():
            shutil.copyfile(current_index, environment["GIT_INDEX_FILE"])
        git(worktree, "add", "-A", env=environment)
        if (worktree / ".ag-check").is_dir():
            git(worktree, "add", "-f", "--", ".ag-check", env=environment)
        return git(worktree, "write-tree", env=environment)


def product_tree(worktree: Path, candidate: str, *, write: bool = False) -> str:
    """Project the verified snapshot onto product files without changing an index."""
    listing = subprocess.run(
        ["git", "-C", str(worktree), "ls-tree", "-z", candidate],
        capture_output=True, check=False,
    )
    if listing.returncode:
        raise ChainBroken("candidate-product-tree-unavailable")
    entries = []
    for entry in listing.stdout.split(b"\0"):
        if not entry:
            continue
        metadata, name = entry.split(b"\t", 1)
        if name == b".ag-check":
            continue
        fields = metadata.split(b" ")
        entries.append(fields[0].lstrip(b"0") + b" " + name + b"\0" + bytes.fromhex(fields[-1].decode("ascii")))
    command = ["git", "-C", str(worktree), "hash-object", "-t", "tree"]
    if write:
        command.append("-w")
    hashed = subprocess.run(command + ["--stdin"], input=b"".join(entries), capture_output=True, check=False)
    if hashed.returncode:
        raise ChainBroken("candidate-product-tree-unavailable")
    return hashed.stdout.decode("ascii").strip()


def _deliver_token_path(key: str) -> Path:
    return ag_home() / "projects" / key / "deliver.token"


def _deliver_token_ok(root: Path) -> bool:
    key = git(root, "config", "--local", "--get", "ag.key", check=False) or project_key(root)
    try:
        expected = _deliver_token_path(key).read_text(encoding="utf-8").strip()
    except OSError:
        return False
    got = os.environ.get("AG_DELIVER_TOKEN") or ""
    if not expected or len(got) != len(expected):
        return False
    return hmac.compare_digest(got, expected)


def _sh() -> str | None:
    found = shutil.which("sh")
    if found:
        return found
    completed = subprocess.run(["git", "--exec-path"], capture_output=True, text=True, check=False)
    exec_path = Path((completed.stdout or "").strip())
    for candidate in (exec_path.parent / "bin" / "sh.exe", exec_path.parent / "bin" / "sh", exec_path / "sh.exe"):
        if candidate.is_file():
            return str(candidate)
    return None


def _run_previous_pre_commit(worktree: Path) -> int:
    previous = git(worktree, "config", "--local", "--get", "ag.previousHooksPath", check=False)
    if not previous or previous == PREV_UNSET:
        return 0
    script = Path(previous) / "pre-commit"
    if not script.is_file():
        return 0
    suffix = script.suffix.lower()
    shell = _sh()
    if suffix in {".exe", ".bat", ".cmd"}:
        command = [str(script)]
    elif shell:
        command = [shell, _posix(script)]
    else:
        sys.stderr.write("ag: previous pre-commit needs sh; refusing deliver\n")
        return 1
    try:
        completed = subprocess.run(command, cwd=str(worktree), check=False, timeout=PREVIOUS_HOOK_TIMEOUT_S)
    except OSError as exc:
        sys.stderr.write(f"ag: previous pre-commit could not run: {exc}\n")
        return 1
    except subprocess.TimeoutExpired:
        sys.stderr.write(f"ag: previous pre-commit timed out after {PREVIOUS_HOOK_TIMEOUT_S}s; refusing deliver\n")
        return 124
    return int(completed.returncode)
