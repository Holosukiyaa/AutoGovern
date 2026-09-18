"""Green delivery loop: worktree, enrolled tests, hook, ff-only. No GUI."""
from __future__ import annotations

import hmac
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from .freeze import freeze_canonical, thaw_canonical
from .hook import hook_main
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
    for name in ("pre-commit", "prepare-commit-msg"):
        path = folder / name
        path.write_text(body, encoding="utf-8")
        try:
            os.chmod(path, 0o755)
        except OSError:
            pass
    return folder


def _ensure_hook_files(key: str) -> Path:
    folder = _hooks_dir(key)
    if (folder / "pre-commit").is_file() and (folder / "prepare-commit-msg").is_file():
        return folder
    return _write_hook(key)


def _hook_ok(root: Path, key: str) -> bool:
    configured = git(root, "config", "--local", "--get", "core.hooksPath", check=False)
    if not configured:
        return False
    folder = _hooks_dir(key)
    return (
        Path(configured).resolve() == folder.resolve()
        and (folder / "pre-commit").is_file()
        and (folder / "prepare-commit-msg").is_file()
    )


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


def _dirty(root: Path) -> bool:
    for line in git(root, "status", "--porcelain", check=False).splitlines():
        path = line[3:].replace("\\", "/").strip().strip('"')
        if path == ".ag" or path.startswith(".ag/"):
            continue
        return True
    return False


def _ticket_paths(worktree: Path, source_head: str) -> list[str]:
    names: list[str] = []
    if source_head:
        for line in git(worktree, "diff", "--name-only", source_head, check=False).splitlines():
            rel = line.replace("\\", "/").strip().strip('"')
            if rel and rel not in names:
                names.append(rel)
    for line in git(worktree, "ls-files", "-o", "--exclude-standard", check=False).splitlines():
        rel = line.replace("\\", "/").strip().strip('"')
        if rel and rel not in names:
            names.append(rel)
    return names


def _probe_red_ids(verify: dict[str, Any] | None) -> list[str]:
    if not isinstance(verify, dict):
        return []
    listed = verify.get("probe_red")
    if isinstance(listed, list) and listed:
        return [str(item) for item in listed if str(item)]
    results = verify.get("probes")
    if not isinstance(results, list):
        return []
    return [
        str(row.get("id") or "")
        for row in results
        if isinstance(row, dict) and row.get("verdict") == "red" and row.get("id")
    ]


def _critic_record(verify: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(verify, dict):
        return {}
    critic = verify.get("critic")
    return critic if isinstance(critic, dict) else {}


def _critic_report_id(verify: dict[str, Any] | None) -> str:
    critic = _critic_record(verify)
    if not critic:
        return ""
    return str(critic.get("report_id") or "").strip()


def _critic_block_message(verify: dict[str, Any] | None) -> str:
    critic = _critic_record(verify)
    if not critic:
        return ""
    rid = _critic_report_id(verify)
    suffix = f"; report_id={rid}" if rid else ""
    outcome = str(critic.get("outcome") or "").strip().casefold()
    if outcome == "rejected":
        return "critic rejected; will not deliver" + suffix
    if outcome == "unavailable" and bool(critic.get("configured")):
        reason = str(critic.get("reason") or "").strip()
        if reason != "not-configured":
            return "critic unavailable; will not deliver" + suffix
    return ""


def _product(test_argv: list[str], verify: dict[str, Any] | None) -> str:
    if _probe_red_ids(verify):
        return "failed"
    if _critic_block_message(verify):
        return "failed"
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
        completed = subprocess.run(command, cwd=str(worktree), check=False)
    except OSError as exc:
        sys.stderr.write(f"ag: previous pre-commit could not run: {exc}\n")
        return 1
    return int(completed.returncode)


def _restore_git_gate(root: Path, previous: str) -> None:
    if previous and previous != PREV_UNSET:
        git(root, "config", "--local", "core.hooksPath", previous)
    else:
        git_run(root, "config", "--local", "--unset", "core.hooksPath")
    git_run(root, "config", "--local", "--unset", "ag.key")
    git_run(root, "config", "--local", "--unset", "ag.previousHooksPath")


def _reset_to(root: Path, sha: str) -> None:
    if git(root, "rev-parse", "HEAD", check=False) != sha:
        git(root, "reset", "--hard", sha)


def _canary_attempt(root: Path, before: str, *, env: dict[str, str], extra: tuple[str, ...] = ()) -> None:
    ran = git_run(root, "commit", "--allow-empty", "-m", CANARY_MSG, *extra, env=env)
    _reset_to(root, before)
    if ran.returncode == 0:
        raise ChainBroken("hook did not refuse canonical commit")
    text = f"{ran.stderr or ''}{ran.stdout or ''}"
    if "canonical" not in text:
        raise ChainBroken(text.strip() or "canonical commit refused for the wrong reason")


def _canary(root: Path) -> None:
    before = git(root, "rev-parse", "HEAD")
    clean = os.environ.copy()
    clean.pop("AG_DELIVER", None)
    clean.pop("AG_DELIVER_TOKEN", None)
    deliver = clean.copy()
    deliver["AG_DELIVER"] = "1"
    _canary_attempt(root, before, env=clean)
    _canary_attempt(root, before, env=deliver)
    _canary_attempt(root, before, env=clean, extra=("--no-verify",))


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
    _ensure_hook_files(key)
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
        "worker_note": (
            "After ag_verify you receive critic.report_id (passed, rejected, or unavailable). "
            "Cite that id when you close the round. You do not receive the critic report body."
        ),
        "task": task,
        "portrait": (task or {}).get("portrait") if task else "",
        "worktree": (task or {}).get("worktree") if task else "",
        "critic_report_id": _critic_report_id(verify if isinstance(verify, dict) else None),
    }
    try:
        from .store import pending_summary

        out["pending_repairs"] = pending_summary(root)
    except Exception:
        out["pending_repairs"] = {"count": 0}
    try:
        from .see import run as see_run

        out["see"] = see_run(root)
    except Exception:
        pass
    return out


def start(root: Path, *, portrait: str = "", skip_pending: bool = False) -> dict[str, Any]:
    """Open a worktree. Tracked canonical files become read-only until finish or abandon."""
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
        try:
            freeze_canonical(root)
        except Exception:
            thaw_canonical(root)
            raise
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
    chosen = str(portrait or "")
    if not skip_pending:
        from .store import pop_pending

        head = pop_pending(root)
        if isinstance(head, dict) and str(head.get("repair_portrait") or "").strip():
            chosen = str(head.get("repair_portrait") or "")
    save_task(
        key,
        {
            "id": task_id,
            "branch": branch,
            "source_head": git(root, "rev-parse", "HEAD"),
            "worktree": str(worktree),
            "portrait": chosen,
            "verified_tree": "",
            "verify": None,
        },
    )
    try:
        freeze_canonical(root)
    except Exception:
        thaw_canonical(root)
        raise
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
    untracked = [
        ln.strip()
        for ln in git(worktree, "ls-files", "-o", "--exclude-standard", check=False).splitlines()
        if ln.strip()
    ]
    record: dict[str, Any] = {
        "exit": 0,
        "stdout": "",
        "stderr": "",
        "undeclared": not test_argv,
        "untracked": untracked[:50],
    }
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
            "untracked": untracked[:50],
        }
    paths = _ticket_paths(worktree, str(task.get("source_head") or ""))
    probe_results: list[Any] = []
    if paths:
        from .probe import run as probe_run

        probe_out = probe_run(Path(state["root"]), paths=paths, awaken=True, tree=worktree)
        raw = probe_out.get("results") if isinstance(probe_out, dict) else []
        probe_results = [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []
    record["probes"] = probe_results
    record["probe_red"] = [
        str(row.get("id") or "") for row in probe_results if row.get("verdict") == "red" and row.get("id")
    ]
    from .probe import missing_fragments

    record["missing"] = missing_fragments(Path(state["root"]), list(record["probe_red"]))
    from .critic import _configured, append_log, critic_run, load_config

    enrolled = Path(state["root"])
    cfg = load_config(enrolled)
    configured = bool(cfg.get("error") or _configured(cfg))
    portrait = str(task.get("portrait") or "").strip()
    task_id = str(task.get("id") or "")
    probe_red = list(record["probe_red"])
    critic: dict[str, Any] = {
        "outcome": "unavailable",
        "reason": "not-configured",
        "store": "",
        "configured": configured,
    }
    logged = False
    if not portrait:
        if configured:
            critic["reason"] = str(cfg.get("error") or "no-exam")
    elif configured:
        try:
            raw = critic_run(
                enrolled,
                exam=portrait,
                tree=worktree,
                task_id=task_id,
                probe_red=probe_red,
            )
            logged = True
            critic = {
                "outcome": str(raw.get("outcome") or "unavailable"),
                "reason": str(raw.get("reason") or ""),
                "store": str(raw.get("store") or ""),
                "prompt_version": str(raw.get("prompt_version") or ""),
                "configured": True,
                "report_id": str(raw.get("report_id") or ""),
            }
            if raw.get("model"):
                critic["model"] = raw["model"]
            if str(raw.get("outcome") or "") == "rejected":
                from .probe import plant_from_reject

                record["probes_planted"] = plant_from_reject(
                    enrolled, items=raw.get("items"), tree=worktree
                )
        except Exception as exc:
            critic = {
                "outcome": "unavailable",
                "reason": f"failed: {exc}",
                "store": "",
                "configured": True,
            }
    if not logged:
        critic["report_id"] = append_log(
            enrolled,
            outcome=str(critic.get("outcome") or "unavailable"),
            reason=str(critic.get("reason") or ""),
            configured=bool(critic.get("configured")),
            store=str(critic.get("store") or ""),
            exam=portrait,
            task_id=task_id,
            probe_red=probe_red,
        )
    record["critic"] = critic
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
    out["probes"] = probe_results
    out["probe_red"] = list(record["probe_red"])
    out["missing"] = list(record["missing"])
    out["critic"] = critic
    out["probes_planted"] = list(record.get("probes_planted") or [])
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
    verify_blob = task.get("verify") if isinstance(task.get("verify"), dict) else None
    red = _probe_red_ids(verify_blob)
    if red:
        usage_note(root, "ship", 6, "block", "probe " + ",".join(red))
        raise ChainBroken("probe red: " + ", ".join(red) + "; will not deliver")
    critic_block = _critic_block_message(verify_blob)
    if critic_block:
        usage_note(root, "ship", 6, "block", critic_block)
        raise ChainBroken(critic_block)
    # Probe/critic refuse keeps freeze (task still open). Thaw only once git must write canonical.
    thaw_canonical(root)
    try:
        return _finish_after_thaw(root, key, state, task, worktree)
    except Exception:
        if load_task(key):
            freeze_canonical(root)
        raise


def _finish_after_thaw(
    root: Path,
    key: str,
    state: dict[str, Any],
    task: dict[str, Any],
    worktree: Path,
) -> dict[str, Any]:
    git(worktree, "add", "-A")
    if git(worktree, "status", "--porcelain", check=False):
        first_line = (str(task.get("portrait") or "").strip().splitlines() or [""])[0][:70]
        title = first_line or f"ag {task.get('id')}"
        token_path = _deliver_token_path(key)
        token = uuid.uuid4().hex
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(token, encoding="utf-8")
        try:
            deliver = os.environ.copy()
            deliver["AG_DELIVER"] = "1"
            deliver["AG_DELIVER_TOKEN"] = token
            git(worktree, "commit", "-m", title, env=deliver)
            usage_note(root, "ship", 4, "help", "AG_DELIVER commit")
        finally:
            try:
                token_path.unlink()
            except OSError:
                pass
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
        "critic_report_id": _critic_report_id(task.get("verify") if isinstance(task.get("verify"), dict) else None),
        "head": git(root, "rev-parse", "HEAD"),
        "hazards": status(root)["hazards"],
    }


def abandon(root: Path) -> dict[str, Any]:
    state = status(root)
    root = Path(state["root"])
    key = str(state["key"])
    task = load_task(key)
    thaw_canonical(root)
    if not task:
        return status(root)
    try:
        _cleanup(root, task)
        save_task(key, None)
    finally:
        thaw_canonical(root)
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
