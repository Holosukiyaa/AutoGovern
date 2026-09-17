"""Green delivery loop: worktree, enrolled tests, hook, ff-only. No GUI."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from .managed import ChainBroken, ag_home, lookup_project, project_key, real_root, load_managed, save_managed
from .see import note as usage_note

SRC = Path(__file__).resolve().parents[1]
PREV_UNSET = "__unset__"
CANARY_MSG = "ag-canary-do-not-keep"


def git_run(cwd: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
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
    path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _hooks_dir(key: str) -> Path:
    return ag_home() / "hooks" / key


def _write_hook(key: str) -> Path:
    folder = _hooks_dir(key)
    folder.mkdir(parents=True, exist_ok=True)
    body = (
        "#!/bin/sh\n"
        f"export AG_HOME='{_posix(ag_home())}'\n"
        f"export PYTHONPATH='{_posix(SRC)}'\n"
        f"'{_posix(Path(sys.executable))}' -m ag hook\n"
        "exit $?\n"
    )
    path = folder / "pre-commit"
    path.write_text(body, encoding="utf-8")
    try:
        os.chmod(path, 0o755)
    except OSError:
        pass
    return folder


def _hook_ok(root: Path, key: str) -> bool:
    configured = git(root, "config", "--local", "--get", "core.hooksPath", check=False)
    if not configured:
        return False
    return Path(configured).resolve() == _hooks_dir(key).resolve() and (_hooks_dir(key) / "pre-commit").is_file()


def _dirty(root: Path) -> bool:
    for line in git(root, "status", "--porcelain", check=False).splitlines():
        path = line[3:].replace("\\", "/").strip().strip('"')
        if path == ".ag" or path.startswith(".ag/"):
            continue
        return True
    return False


def _product(test_argv: list[str], verify: dict[str, Any] | None) -> str:
    if not test_argv:
        return "undeclared"
    if not verify or "exit" not in verify:
        return "pending"
    if int(verify["exit"]) == 0:
        return "passed"
    return "failed"


def _process(task: dict[str, Any] | None) -> str:
    if not task:
        return "idle"
    if task.get("verified_tree"):
        return "verified"
    return "active"


def tree_digest(worktree: Path) -> str:
    git(worktree, "add", "-A")
    return git(worktree, "write-tree")


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
    shell = _sh()
    command = [shell, _posix(script)] if shell else [str(script)]
    completed = subprocess.run(command, cwd=str(worktree), check=False)
    return int(completed.returncode)


def _restore_git_gate(root: Path, previous: str) -> None:
    if previous and previous != PREV_UNSET:
        git(root, "config", "--local", "core.hooksPath", previous)
    else:
        git_run(root, "config", "--local", "--unset", "core.hooksPath")
    git_run(root, "config", "--local", "--unset", "ag.key")
    git_run(root, "config", "--local", "--unset", "ag.previousHooksPath")


def _undo_canary_commit(root: Path) -> None:
    if git(root, "log", "-1", "--format=%s", check=False) == CANARY_MSG:
        git(root, "reset", "--hard", "HEAD~1")


def _canary(root: Path) -> None:
    deliver = os.environ.copy()
    deliver["AG_DELIVER"] = "1"
    for env in (None, deliver):
        ran = git_run(root, "commit", "--allow-empty", "-m", CANARY_MSG, env=env)
        _undo_canary_commit(root)
        if ran.returncode == 0:
            raise ChainBroken("hook did not refuse canonical commit")
        text = f"{ran.stderr or ''}{ran.stdout or ''}"
        if "canonical" not in text:
            raise ChainBroken(text.strip() or "canonical commit refused for the wrong reason")


def _drop_project(key: str) -> None:
    blob = load_managed()
    blob["projects"] = [row for row in blob["projects"] if not (isinstance(row, dict) and str(row.get("key") or "") == key)]
    save_managed(blob)


def enroll(root: Path, *, test_argv: list[str] | None = None, note: str = "") -> dict[str, Any]:
    root = real_root(root)
    if not root.is_dir():
        raise ChainBroken(f"not a directory: {root}")
    git(root, "rev-parse", "--is-inside-work-tree")
    if not _is_canonical(root):
        raise ChainBroken("enroll the canonical checkout, not a worktree")
    if _dirty(root):
        raise ChainBroken("cannot enroll while canonical is dirty")
    key = project_key(root)
    item = lookup_project(root)
    first = item is None
    current = git(root, "config", "--local", "--get", "core.hooksPath", check=False)
    ours = _hooks_dir(key)
    if item and str(item.get("previous_hooks_path") or ""):
        previous = str(item["previous_hooks_path"])
    elif current and Path(current).resolve() != ours.resolve():
        previous = current
    else:
        previous = PREV_UNSET
    blob = load_managed()
    payload = {
        "root": str(root),
        "real": str(root),
        "key": key,
        "note": str(note or (item or {}).get("note") or ""),
        "test_argv": list(test_argv) if test_argv is not None else list((item or {}).get("test_argv") or []),
        "previous_hooks_path": previous,
    }
    wanted = str(root)
    found = False
    for row in blob["projects"]:
        if not isinstance(row, dict):
            continue
        stored = str(row.get("real") or row.get("root") or "")
        if stored and str(real_root(Path(stored))) == wanted:
            row.update(payload)
            found = True
            break
    if not found:
        blob["projects"].append(payload)
    save_managed(blob)
    hooks = _write_hook(key)
    git(root, "config", "--local", "ag.key", key)
    git(root, "config", "--local", "ag.previousHooksPath", previous)
    git(root, "config", "--local", "core.hooksPath", _posix(hooks))
    try:
        _canary(root)
    except ChainBroken:
        usage_note(root, "ship", 9, "block", "hook did not refuse canonical")
        if first:
            _restore_git_gate(root, previous)
            _drop_project(key)
        raise
    usage_note(root, "ship", 9, "help", "canonical commit refused")
    return status(root)


def status(root: Path) -> dict[str, Any]:
    root = real_root(root)
    item = lookup_project(root)
    if item is None:
        raise ChainBroken(f"not enrolled: {root}")
    key = str(item.get("key") or project_key(root))
    test_argv = [str(x) for x in (item.get("test_argv") or [])]
    task = load_task(key)
    verify = task.get("verify") if isinstance(task, dict) else None
    hook_ok = _hook_ok(root, key)
    dirty = _dirty(root)
    hazards: list[str] = []
    if not hook_ok:
        hazards.append("hook-removed")
    if dirty:
        hazards.append("canonical-dirty")
    if task:
        product = _product(test_argv, verify if isinstance(verify, dict) else None)
        process = _process(task)
    elif not test_argv:
        product = str(item.get("last_product") or "undeclared")
        process = str(item.get("last_process") or "idle")
    else:
        product = str(item.get("last_product") or "pending")
        process = str(item.get("last_process") or "idle")
    out = {
        "schema": "ag.status.v1",
        "root": str(root),
        "key": key,
        "managed": True,
        "hook_ok": hook_ok,
        "canonical_dirty": dirty,
        "hazards": hazards,
        "test_argv": test_argv,
        "process": process,
        "product": product,
        "reminder": "process complete is not product passed",
        "task": task,
        "portrait": (task or {}).get("portrait") if task else "",
        "worktree": (task or {}).get("worktree") if task else "",
    }
    try:
        from .see import run as see_run

        out["see"] = see_run(root)
    except Exception:
        pass
    return out


def start(root: Path, *, portrait: str = "") -> dict[str, Any]:
    state = status(root)
    root = Path(state["root"])
    key = str(state["key"])
    if state["canonical_dirty"]:
        usage_note(root, "ship", 8, "block", "start canonical dirty")
        raise ChainBroken("canonical checkout is dirty; not a work site")
    if not state["hook_ok"]:
        usage_note(root, "ship", 8, "block", "start hook missing")
        raise ChainBroken("hook is not installed; re-enroll")
    existing = load_task(key)
    if existing and Path(str(existing.get("worktree") or "")).is_dir():
        return status(root)
    if existing:
        save_task(key, None)
    if not _is_canonical(root):
        raise ChainBroken("start from the canonical checkout")
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if branch in {"HEAD", ""}:
        raise ChainBroken("canonical HEAD is detached")
    task_id = uuid.uuid4().hex[:8]
    worktree = ag_home() / "worktrees" / key / task_id
    worktree.parent.mkdir(parents=True, exist_ok=True)
    git(root, "worktree", "add", "-b", f"ag/{task_id}", str(worktree), "HEAD")
    save_task(
        key,
        {
            "id": task_id,
            "branch": branch,
            "source_head": git(root, "rev-parse", "HEAD"),
            "worktree": str(worktree),
            "portrait": str(portrait or ""),
            "verified_tree": "",
            "verify": None,
        },
    )
    usage_note(root, "ship", 2, "help", "opened")
    return status(root)


def verify(root: Path) -> dict[str, Any]:
    state = status(root)
    key = str(state["key"])
    task = load_task(key)
    if not task:
        raise ChainBroken("no open task; ag_start first")
    worktree = Path(str(task.get("worktree") or ""))
    if not worktree.is_dir():
        raise ChainBroken(f"worktree missing: {worktree}")
    test_argv = [str(x) for x in (state.get("test_argv") or [])]
    record: dict[str, Any] = {"exit": 0, "stdout": "", "stderr": "", "undeclared": not test_argv}
    if test_argv:
        completed = subprocess.run(
            test_argv,
            cwd=str(worktree),
            capture_output=True,
            text=True,
            check=False,
        )
        record = {
            "exit": int(completed.returncode),
            "stdout": (completed.stdout or "")[-4000:],
            "stderr": (completed.stderr or "")[-4000:],
            "undeclared": False,
        }
    digest = tree_digest(worktree)
    task["verify"] = record
    task["verified_tree"] = digest if record["exit"] == 0 else ""
    save_task(key, task)
    if record.get("undeclared"):
        usage_note(root, "ship", 1, "help", "verify without tests")
    elif record["exit"] == 0:
        usage_note(root, "ship", 6, "help", "tests passed")
        usage_note(root, "ship", 7, "help", "pinned")
    else:
        usage_note(root, "ship", 6, "block", f"exit {record['exit']}")
    out = status(root)
    out["verify"] = record
    out["verified_tree"] = task["verified_tree"]
    try:
        from .lift import run as lift_run

        out["lift"] = lift_run(root)
    except Exception:
        pass
    return out


def _cleanup(root: Path, task: dict[str, Any]) -> None:
    worktree = Path(str(task.get("worktree") or ""))
    task_id = str(task.get("id") or "")
    if worktree.is_dir():
        git(root, "worktree", "remove", "--force", str(worktree), check=False)
    if task_id:
        git(root, "branch", "-D", f"ag/{task_id}", check=False)


def finish(root: Path) -> dict[str, Any]:
    state = status(root)
    root = Path(state["root"])
    key = str(state["key"])
    task = load_task(key)
    if not task:
        raise ChainBroken("no open task")
    if not state["hook_ok"]:
        usage_note(root, "ship", 8, "block", "finish hook-removed")
        raise ChainBroken("hook-removed: will not deliver")
    if state["canonical_dirty"]:
        usage_note(root, "ship", 8, "block", "finish canonical dirty")
        raise ChainBroken("canonical is dirty; will not deliver")
    current = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if current != str(task.get("branch") or ""):
        raise ChainBroken(f"canonical is on {current}, task started on {task.get('branch')}")
    worktree = Path(str(task.get("worktree") or ""))
    if not worktree.is_dir():
        raise ChainBroken("worktree missing")
    if not task.get("verified_tree"):
        raise ChainBroken("not verified")
    digest = tree_digest(worktree)
    if digest != task.get("verified_tree"):
        usage_note(root, "ship", 7, "block", "mismatch")
        raise ChainBroken("tree digest mismatch; run ag_verify again")
    git(worktree, "add", "-A")
    if git(worktree, "status", "--porcelain", check=False):
        first_line = (str(task.get("portrait") or "").strip().splitlines() or [""])[0][:70]
        title = first_line or f"ag {task.get('id')}"
        deliver = os.environ.copy()
        deliver["AG_DELIVER"] = "1"
        git(worktree, "commit", "-m", title, env=deliver)
        usage_note(root, "ship", 4, "help", "AG_DELIVER commit")
    try:
        git(root, "merge", "--ff-only", f"ag/{task.get('id')}")
    except ChainBroken:
        usage_note(root, "ship", 5, "block", "merge")
        raise
    usage_note(root, "ship", 5, "help", "merged")
    usage_note(root, "ship", 7, "help", "matched")
    portrait = str(task.get("portrait") or "")
    product = _product([str(x) for x in (state.get("test_argv") or [])], task.get("verify") if isinstance(task.get("verify"), dict) else None)
    _cleanup(root, task)
    save_task(key, None)
    blob = load_managed()
    for row in blob["projects"]:
        if isinstance(row, dict) and str(row.get("key") or "") == key:
            row["last_product"] = product
            row["last_process"] = "completed"
            break
    save_managed(blob)
    if product == "undeclared":
        usage_note(root, "ship", 1, "help", "finish undeclared")
    elif product == "passed":
        usage_note(root, "ship", 6, "help", "finish passed")
    return {
        "schema": "ag.finish.v1",
        "root": str(root),
        "process": "completed",
        "product": product,
        "reminder": "process complete is not product passed",
        "portrait": portrait,
        "head": git(root, "rev-parse", "HEAD"),
        "hazards": status(root)["hazards"],
    }


def abandon(root: Path) -> dict[str, Any]:
    state = status(root)
    root = Path(state["root"])
    key = str(state["key"])
    task = load_task(key)
    if not task:
        return status(root)
    _cleanup(root, task)
    save_task(key, None)
    return status(root)


def unenroll(root: Path) -> dict[str, Any]:
    state = status(root)
    root = Path(state["root"])
    key = str(state["key"])
    if load_task(key):
        raise ChainBroken("abandon the open task before unenroll")
    item = lookup_project(root) or {}
    previous = str(
        item.get("previous_hooks_path")
        or git(root, "config", "--local", "--get", "ag.previousHooksPath", check=False)
        or PREV_UNSET
    )
    _restore_git_gate(root, previous)
    _drop_project(key)
    shutil.rmtree(_hooks_dir(key), ignore_errors=True)
    usage_note(root, "ship", 11, "help", "restored hooksPath")
    return {
        "schema": "ag.unenroll.v1",
        "root": str(root),
        "unenrolled": True,
        "restored_hooksPath": None if previous == PREV_UNSET else previous,
    }


def hook_main() -> int:
    try:
        toplevel = Path(git(Path.cwd(), "rev-parse", "--show-toplevel"))
        canonical = _canonical_root(toplevel)
    except ChainBroken:
        return 0
    if lookup_project(canonical) is None:
        return 0
    if _is_canonical(toplevel):
        usage_note(canonical, "ship", 3, "block", "canonical commit")
        sys.stderr.write("ag: canonical checkout is not a work site; use ag_start\n")
        return 1
    if os.environ.get("AG_DELIVER") != "1":
        usage_note(canonical, "ship", 4, "block", "worktree commit")
        sys.stderr.write("ag: only ag_finish can commit\n")
        return 1
    from .catalog import enabled

    if not enabled(canonical, "ship", 10):
        return 0
    code = _run_previous_pre_commit(toplevel)
    previous = git(toplevel, "config", "--local", "--get", "ag.previousHooksPath", check=False)
    if previous and previous != PREV_UNSET:
        usage_note(canonical, "ship", 10, "help", f"exit {code}")
    return code
