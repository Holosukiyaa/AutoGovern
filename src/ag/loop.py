"""Green delivery loop: worktree, enrolled tests, hook, ff-only. No GUI."""
from __future__ import annotations

import hmac
import json
import os
import time
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from .freeze import freeze_canonical, thaw_canonical
from .hook import hook_main
from .switch import block_message as _switch_block_message
from .switch import report_id_from_verify as _switch_report_id
from .store import append_task_step, ensure_start_step, latest_timeline_path
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


def _hook_src(enrolled: Path | None = None) -> Path:
    if enrolled is not None:
        candidate = Path(enrolled) / "src"
        if (candidate / "ag").is_dir():
            return candidate
    return SRC


def _write_hook(key: str, enrolled: Path | None = None) -> Path:
    folder = _hooks_dir(key)
    folder.mkdir(parents=True, exist_ok=True)
    body = (
        "#!/bin/sh\n"
        f"export AG_HOME='{_posix(ag_home())}'\n"
        f"export PYTHONPATH='{_posix(_hook_src(enrolled))}'\n"
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


def _ensure_hook_files(key: str, enrolled: Path | None = None) -> Path:
    return _write_hook(key, enrolled)


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


def _product(test_argv: list[str], verify: dict[str, Any] | None) -> str:
    if _probe_red_ids(verify):
        return "failed"
    if not verify or "exit" not in verify:
        return "pending"
    if test_argv and int(verify["exit"]) != 0:
        return "failed"
    if _switch_block_message(verify):
        return "failed"
    if not test_argv:
        return "undeclared"
    return "passed"


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
    hooks = _write_hook(key, root)
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


def parse_anchors(portrait: str) -> list[dict[str, Any]]:
    """Parse anchor lines from a portrait. AI guesses never become hard anchors."""
    valid_kinds = {"soft", "hard", "discoverable", "blocking", "defaulted", "avoid", "obsolete"}
    markers = {"!": "hard", "?": "blocking", "~": "discoverable", "=": "defaulted", "-": "avoid", "x": "obsolete"}
    anchors: list[dict[str, Any]] = []
    for raw in str(portrait or "").splitlines():
        line = raw.strip()
        if not line.lower().startswith("anchor"):
            continue
        if ":" in line:
            prefix, body = line.split(":", 1)
        elif chr(0xff1a) in line:
            prefix, body = line.split(chr(0xff1a), 1)
        else:
            continue
        body = body.strip()
        if not body:
            continue
        marker = prefix.strip().lower()[-1:]
        kind = markers.get(marker, "soft")
        if kind not in valid_kinds:
            kind = "soft"
        anchors.append({"id": f"a{len(anchors) + 1}", "text": body, "kind": kind})
    return anchors

def _anchor_exam(task: dict[str, Any]) -> str:
    anchors = task.get("anchors") if isinstance(task.get("anchors"), list) else []
    if not anchors:
        return ""
    lines = ["意图锚点："]
    for index, item in enumerate(anchors, 1):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or ("hard" if item.get("hard") else "soft"))
        lines.append(f"[{kind}] {item.get('text') or ''}")
    return "\n".join(lines)


def status(root: Path) -> dict[str, Any]:
    root = real_root(root)
    item = lookup_project(root)
    if item is None:
        raise ChainBroken(f"not enrolled: {root}")
    key = str(item.get("key") or project_key(root))
    _ensure_hook_files(key, root)
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
        "worker_note": "After ag_verify cite critic.report_id and switch.report_id. No report bodies. Switch is the finish gate; critic is not.",
        "task": task,
        "portrait": (task or {}).get("portrait") if task else "",
        "anchors": (task or {}).get("anchors") if task else [],
        "anchor_map_path": (task or {}).get("anchor_map_path") if task else "",
        "worktree": (task or {}).get("worktree") if task else "",
        "critic_report_id": _critic_report_id(verify if isinstance(verify, dict) else None),
        "switch_report_id": _switch_report_id(verify if isinstance(verify, dict) else None),
        "timeline_path": str(latest_timeline_path(root, str((task or {}).get("id") or "")) or latest_timeline_path(root) or ""),
        "subagent": {
            "optional": True,
            "ready": False,
            "min_workers": 1,
            "max_workers": 3,
            "contract": "ag.worker.task.v1 / ag.worker.result.v1",
            "note": "Show the anchor preview to the user, run confirm-map only after user approval, then create 1-3 workers. Workers write only their isolated worktree and cannot finish or merge.",
        },
    }
    if task:
        try:
            from .anchor_map import render_map, render_unicode

            anchors = [dict(item) for item in (task.get("anchors") or []) if isinstance(item, dict)]
            current_anchor = str(task.get("current_anchor") or (anchors[0].get("id") if anchors else ""))
            anchor_map_text = str(task.get("anchor_map_path") or "").strip()
            anchor_map_path = Path(anchor_map_text)
            if anchor_map_text:
                render_map(
                    title=f"ag-{task.get('id') or 'task'}",
                    portrait=str(task.get("portrait") or ""),
                    out=anchor_map_path,
                    anchors=anchors,
                    current_anchor=current_anchor,
                )
            if not anchor_map_text:
                raise ChainBroken("active task has no anchor map path")
            anchor_preview_text = str(task.get("anchor_preview_path") or "").strip()
            anchor_preview_path = Path(anchor_preview_text) if anchor_preview_text else anchor_map_path.with_suffix(".txt")
            anchor_preview_path.parent.mkdir(parents=True, exist_ok=True)
            anchor_preview = render_unicode(f"ag-{task.get('id') or 'task'}", anchors, current_anchor)
            anchor_preview_path.write_text(anchor_preview, encoding="utf-8")
            task["anchor_preview_path"] = str(anchor_preview_path.resolve())
            task["anchor_preview"] = anchor_preview
            task["current_anchor"] = current_anchor
            save_task(key, task)
            out["anchor_preview_path"] = task["anchor_preview_path"]
            out["anchor_preview"] = anchor_preview
            out["current_anchor"] = current_anchor
            out["intent_map_confirmed"] = bool(task.get("intent_map_confirmed"))
            out["subagent"]["ready"] = bool(task.get("intent_map_confirmed"))
        except Exception:
            pass
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


def start(root: Path, *, portrait: str = "", anchors: list[dict[str, Any]] | None = None, skip_pending: bool = False) -> dict[str, Any]:
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
    from .anchor_map import render_map

    task_anchors = parse_anchors(chosen) if anchors is None else [dict(item) for item in (anchors or []) if isinstance(item, dict)]
    if not chosen.strip() or not task_anchors:
        usage_note(root, "ship", 8, "block", "start without intent anchors")
        raise ChainBroken("intent sync required: provide portrait with at least one anchor line")
    anchor_map = render_map(
        title=f"ag-{task_id}",
        portrait=chosen,
        out=worktree / ".ag-artifacts" / "anchor-maps" / f"ag-{task_id}.svg",
        anchors=task_anchors,
        current_anchor=(task_anchors or [{}])[0].get("id", ""),
    )
    save_task(
        key,
        {
            "id": task_id,
            "branch": branch,
            "source_head": git(root, "rev-parse", "HEAD"),
            "worktree": str(worktree),
            "portrait": chosen,
            "anchors": task_anchors,
            "anchor_map_path": str(anchor_map.resolve()),
            "anchor_preview_path": str(anchor_map.with_suffix(".txt").resolve()),
            "intent_map_confirmed": False,
            "current_anchor": (task_anchors or [{}])[0].get("id", ""),
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
    line = (chosen.strip().splitlines() or [""])[0][:80]
    append_task_step(root, task_id, "start", portrait_line=line, worktree=str(worktree))
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
    task_id = str(task.get("id") or "")
    enrolled = Path(state["root"])
    ensure_start_step(enrolled, task_id, task.get("portrait"), worktree)
    test_argv = [str(x) for x in (state.get("test_argv") or [])]
    untracked = [
        ln.strip()
        for ln in git(worktree, "ls-files", "-o", "--exclude-standard", check=False).splitlines()
        if ln.strip()
    ]
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    try:
        from .gui import write_live

        write_live(enrolled, phase="tests", timings=timings)
    except Exception:
        pass
    record: dict[str, Any] = {
        "exit": 0,
        "stdout": "",
        "stderr": "",
        "undeclared": not test_argv,
        "untracked": untracked[:50],
    }
    t_tests = time.perf_counter()
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
    timings["tests_s"] = round(time.perf_counter() - t_tests, 3)
    append_task_step(enrolled, task_id, "verify-tests", seconds=timings["tests_s"])
    try:
        from .gui import write_live

        write_live(enrolled, phase="probes", timings=timings)
    except Exception:
        pass
    paths = _ticket_paths(worktree, str(task.get("source_head") or ""))
    probe_results: list[Any] = []
    if paths:
        from .probe import run as probe_run

        probe_out = probe_run(Path(state["root"]), paths=paths, awaken=True, tree=worktree)
        raw = probe_out.get("results") if isinstance(probe_out, dict) else []
        probe_results = [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []
    record["evidence"] = {
        "tests": {
            "declared": not bool(record.get("undeclared")),
            "exit": record.get("exit"),
            "stdout_tail": str(record.get("stdout") or "")[-1200:],
            "stderr_tail": str(record.get("stderr") or "")[-1200:],
        },
        "probes": [
            {
                "id": row.get("id"),
                "verdict": row.get("verdict"),
                "exit": row.get("exit"),
                "tail": str(row.get("tail") or "")[-600:],
            }
            for row in probe_results
            if isinstance(row, dict)
        ],
    }
    record["probes"] = probe_results
    record["probe_red"] = [
        str(row.get("id") or "") for row in probe_results if row.get("verdict") == "red" and row.get("id")
    ]
    from .probe import missing_fragments

    record["missing"] = missing_fragments(Path(state["root"]), list(record["probe_red"]))
    worker_root = worktree / ".ag-artifacts" / "workers"
    worker_dirs = [item for item in worker_root.iterdir() if item.is_dir()] if worker_root.is_dir() else []
    missing_worker_results: list[str] = []
    for worker_path in worker_dirs:
        if not (worker_path / "task.json").is_file():
            continue
        if not (worker_path / "result.json").is_file():
            missing_worker_results.append(worker_path.name)
    if missing_worker_results:
        record["exit"] = 1
        record["stderr"] = (
            (record.get("stderr") or "")
            + ("\n" if record.get("stderr") else "")
            + "missing worker results: " + ", ".join(missing_worker_results)
        )
        record["missing_worker_results"] = missing_worker_results
    record["evidence"]["workers"] = {
        "count": len(worker_dirs),
        "missing_results": missing_worker_results,
    }
    timings["probes_s"] = round(time.perf_counter() - t_tests - timings["tests_s"], 3)
    append_task_step(enrolled, task_id, "verify-probes", probe_red=list(record["probe_red"]), seconds=timings["probes_s"])
    try:
        from .gui import write_live

        write_live(enrolled, phase="critic", timings=timings)
    except Exception:
        pass
    from .critic import attach_verify

    portrait = str(task.get("portrait") or "").strip()
    anchor_exam = _anchor_exam(task)
    if anchor_exam:
        portrait = f"{portrait}\n\n{anchor_exam}" if portrait else anchor_exam
    probe_red = list(record["probe_red"])
    critic, planted = attach_verify(
        enrolled,
        worktree=worktree,
        portrait=portrait,
        task_id=task_id,
        probe_red=probe_red,
        tests_failed=bool(test_argv) and int(record.get("exit") or 0) != 0,
    )
    if planted:
        record["probes_planted"] = planted
    record["critic"] = critic
    record["evidence"]["critic"] = {
        "outcome": critic.get("outcome"),
        "report_id": critic.get("report_id"),
        "store": critic.get("store"),
        "model": critic.get("model"),
    }
    timings["critic_s"] = round(time.perf_counter() - t0 - timings.get("tests_s", 0) - timings.get("probes_s", 0), 3)
    append_task_step(enrolled, task_id, "verify-critic", report_id=str(critic.get("report_id") or ""), outcome=str(critic.get("outcome") or ""), seconds=timings["critic_s"])
    from .switch import attach_verify as attach_switch

    switch = attach_switch(
        enrolled,
        worktree=worktree,
        portrait=portrait,
        task_id=task_id,
        probe_red=probe_red,
        critic=critic,
        tests_failed=bool(test_argv) and int(record.get("exit") or 0) != 0,
    )
    record["switch"] = switch
    record["evidence"]["switch"] = {
        "outcome": switch.get("outcome"),
        "report_id": switch.get("report_id"),
        "store": switch.get("store"),
        "model": switch.get("model"),
    }
    timings["switch_s"] = round(time.perf_counter() - t0 - timings.get("tests_s", 0) - timings.get("probes_s", 0) - timings.get("critic_s", 0), 3)
    append_task_step(enrolled, task_id, "verify-switch", report_id=str(switch.get("report_id") or ""), outcome=str(switch.get("outcome") or ""), seconds=timings["switch_s"])
    timings["total_s"] = round(time.perf_counter() - t0, 3)
    record["timings"] = timings
    record["evidence"]["anchor_map_path"] = str(task.get("anchor_map_path") or "")
    record["evidence"]["anchor_preview_path"] = str(task.get("anchor_preview_path") or "")
    record["evidence"]["anchor_preview"] = str(task.get("anchor_preview") or "")
    record["evidence"]["current_anchor"] = task.get("current_anchor") or ""
    record["evidence"]["timings"] = dict(timings)
    try:
        from .gui import write_dashboard

        write_dashboard(enrolled, browse=False)
    except Exception:
        pass
    digest = tree_digest(worktree)
    route_anchors = [item for item in (task.get("anchors") or []) if isinstance(item, dict) and str(item.get("kind") or "soft") not in {"blocking", "avoid"}]
    task["current_anchor"] = str((route_anchors[-1] if route_anchors else {}).get("id") or "")
    task["verify"] = record
    task["verified_tree"] = digest if record["exit"] == 0 else ""
    record["evidence"]["verified_tree"] = task["verified_tree"]
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
    out["switch"] = switch
    out["switch_report_id"] = str(switch.get("report_id") or "")
    out["probes_planted"] = list(record.get("probes_planted") or [])
    out["timings"] = dict(record.get("timings") or {})
    out["evidence"] = {
        "tests": {
            "declared": not bool(record.get("undeclared")),
            "exit": record.get("exit"),
            "stdout_tail": str(record.get("stdout") or "")[-1200:],
            "stderr_tail": str(record.get("stderr") or "")[-1200:],
        },
        "probes": [
            {
                "id": row.get("id"),
                "verdict": row.get("verdict"),
                "exit": row.get("exit"),
                "tail": str(row.get("tail") or "")[-600:],
            }
            for row in probe_results
            if isinstance(row, dict)
        ],
        "critic": {
            "outcome": critic.get("outcome"),
            "report_id": critic.get("report_id"),
            "store": critic.get("store"),
            "model": critic.get("model"),
        },
        "switch": {
            "outcome": switch.get("outcome"),
            "report_id": switch.get("report_id"),
            "store": switch.get("store"),
            "model": switch.get("model"),
        },
        "anchor_map_path": str((task or {}).get("anchor_map_path") or ""),
        "anchor_preview_path": str((task or {}).get("anchor_preview_path") or ""),
        "anchor_preview": str((task or {}).get("anchor_preview") or ""),
        "current_anchor": str((task or {}).get("current_anchor") or ""),
        "workers": dict((task.get("verify") or {}).get("evidence", {}).get("workers", {})),
        "verified_tree": task.get("verified_tree") or "",
        "timings": dict(record.get("timings") or {}),
    }
    try:
        from .lift import run as lift_run

        out["lift"] = lift_run(root)
    except Exception:
        pass
    return out


def confirm_map(root: Path) -> dict[str, Any]:
    state = status(root)
    key = str(state["key"])
    task = load_task(key)
    if not task:
        raise ChainBroken("no open task; ag_start first")
    if not bool(task.get("intent_map_confirmed")):
        task["intent_map_confirmed"] = True
        save_task(key, task)
        append_task_step(root, str(task.get("id") or ""), "intent-map-confirmed")
    return status(root)


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

    def _no(reason: str, lane: int = 6, detail: str = "") -> None:
        usage_note(root, "ship", lane, "block", detail or reason)
        append_task_step(root, str(task.get("id") or ""), "finish-refused", reason=reason)
        raise ChainBroken(reason)

    if not state["hook_ok"]:
        _no("hook-removed: will not deliver", 8, "finish hook-removed")
    if state["canonical_dirty"]:
        _no("canonical is dirty; will not deliver", 8, "finish canonical dirty")
    current = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if current != str(task.get("branch") or ""):
        _no(f"canonical is on {current}, task started on {task.get('branch')}")
    worktree = Path(str(task.get("worktree") or ""))
    if not worktree.is_dir():
        _no("worktree missing")
    if not task.get("verified_tree"):
        _no("not verified")
    digest = tree_digest(worktree)
    if digest != task.get("verified_tree"):
        _no("tree digest mismatch; run ag_verify again", 7, "mismatch")
    verify_blob = task.get("verify") if isinstance(task.get("verify"), dict) else None
    red = _probe_red_ids(verify_blob)
    if red:
        _no("probe red: " + ", ".join(red) + "; will not deliver", 6, "probe " + ",".join(red))
    switch_block = _switch_block_message(verify_blob)
    if switch_block:
        _no(switch_block)
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
        append_task_step(root, str(task.get("id") or ""), "finish-refused", reason="merge")
        raise
    usage_note(root, "ship", 5, "help", "merged")
    usage_note(root, "ship", 7, "help", "matched")
    portrait = str(task.get("portrait") or "")
    product = _product([str(x) for x in (state.get("test_argv") or [])], task.get("verify") if isinstance(task.get("verify"), dict) else None)
    head = git(root, "rev-parse", "HEAD")
    vblob = task.get("verify") if isinstance(task.get("verify"), dict) else None
    anchors = [dict(item) for item in (task.get("anchors") or []) if isinstance(item, dict)]
    current_anchor = str(task.get("current_anchor") or (anchors[0].get("id") if anchors else ""))
    anchor_progress = {
        "anchors": anchors,
        "anchor_map_path": str(task.get("anchor_map_path") or ""),
        "anchor_preview_path": str(task.get("anchor_preview_path") or ""),
        "anchor_preview": str(task.get("anchor_preview") or ""),
        "current_anchor": current_anchor,
        "reminder": "Before accepting delivery, re-read the intent map and compare each anchor with the final result; soft anchors are not auto-completion states.",
    }
    append_task_step(root, str(task.get("id") or ""), "finish", head=head, product=product, critic_report_id=_critic_report_id(vblob), switch_report_id=_switch_report_id(vblob), anchor_progress=anchor_progress)
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
        "anchor_progress": anchor_progress,
        "critic_report_id": _critic_report_id(task.get("verify") if isinstance(task.get("verify"), dict) else None),
        "switch_report_id": _switch_report_id(task.get("verify") if isinstance(task.get("verify"), dict) else None),
        "head": head,
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
