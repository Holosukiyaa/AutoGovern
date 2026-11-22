"""Zero-token site facts, stop/resume and objective handoff/backbrief handling."""
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Any

from .freeze import freeze_worktree, thaw_worktree
from .managed import ChainBroken, lookup_project, project_key, real_root
from .store import append_task_step
from .ticket_package import atomic_write, sealed_dir

EXEMPT = {"abandon", "andon", "handoff", "backbrief", "confirm-map"}

_command_site: ContextVar[dict[str, Any] | None] = ContextVar("ag_command_site", default=None)


@contextmanager
def command_scope(root: Path | None, command: str):
    token = _command_site.set(None)
    try:
        view = before_command(root, command) if root is not None else None
        _command_site.set(view)
        yield
    finally:
        _command_site.reset(token)


def include_site(result: Any) -> Any:
    view = _command_site.get()
    if view is not None and isinstance(result, dict):
        return {"site": view, **result}
    return result


def dumps(result: Any, **kwargs: Any) -> str:
    return json.dumps(include_site(result), **kwargs)



def matches(path: str, pattern: str) -> bool:
    """Segment globs: * stays in one directory, ** spans zero or more directories."""
    parts, patterns = path.split("/"), pattern.split("/")

    @lru_cache(None)
    def walk(i: int, j: int) -> bool:
        if j == len(patterns):
            return i == len(parts)
        if patterns[j] == "**":
            return walk(i, j + 1) or (i < len(parts) and walk(i + 1, j))
        return i < len(parts) and fnmatch.fnmatchcase(parts[i], patterns[j]) and walk(i + 1, j + 1)

    return walk(0, 0)


def _git(tree: Path, *args: str) -> bytes:
    done = subprocess.run(["git", "--no-optional-locks", "-C", str(tree), *args], capture_output=True)
    if done.returncode:
        raise ChainBroken("site-source-error: " + done.stderr.decode("utf-8", "replace").strip())
    return done.stdout


def _product(path: str) -> bool:
    return path != ".ag-check" and not path.startswith(".ag-check/")


def snapshot(root: Path, task: dict[str, Any]) -> dict[str, Any] | None:
    if not task.get("package_spec") or not Path(task.get("worktree", "")).is_dir():
        return None
    tree = Path(task["worktree"])
    # Scope comes from the sealed package, never from a caller-supplied policy.
    try:
        spec = json.loads((sealed_dir(root, task["id"]) / "spec.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # Existing package-integrity diagnostics remain authoritative.
    changed = {os.fsdecode(p) for p in _git(tree, "diff", "-z", "--name-only", task["source_head"]).split(b"\0") if p}
    untracked = {os.fsdecode(p) for p in _git(tree, "ls-files", "-o", "--exclude-standard", "-z").split(b"\0") if p}
    changed = sorted(p for p in changed | untracked if _product(p))
    lines = 0
    stats = iter(_git(tree, "diff", "--numstat", "-z", task["source_head"]).split(b"\0"))
    for entry in stats:
        if not entry:
            continue
        added, removed, name = entry.split(b"\t", 2)
        if not name:  # Rename numstat has two NUL-delimited names after the counts.
            next(stats)
            name = next(stats)
        if _product(os.fsdecode(name)):
            lines += sum(int(n) for n in (added, removed) if n.isdigit())
    for name in untracked:
        if _product(name):
            path = tree / name
            if path.is_symlink():
                lines += len(os.readlink(path).splitlines())
            elif path.is_file():
                lines += len(path.read_bytes().splitlines())
    scope, budget = spec["scope"], spec["budget"]
    outside = [p for p in changed if any(matches(p, pat) for pat in scope.get("deny", []))
               or not any(matches(p, pat) for pat in scope["allow"] + scope.get("docs", []))]
    ratio = max(len(changed) / budget["files"], lines / budget["lines"])
    reminders = []
    if ratio > 1:
        reminders.append(f"预算已超过 100%（{ratio:.0%}）；超过 150% 将停工，请核对范围并拉安灯。")
    elif ratio >= .7:
        reminders.append(f"预算已使用 {ratio:.0%}（达到 70%）；请核对剩余结果。")
    return {"changed": changed, "out_of_scope": outside,
            "budget": {"files": len(changed), "lines": lines, "ratio": ratio},
            "reminders": reminders, "stop": task.get("site_stop") or None}


def product_files(tree: Path, revision: str) -> dict[str, str]:
    """Read blob identities from a saved tree, including untracked product files."""
    files = {}
    for entry in _git(tree, "ls-tree", "-rz", revision).split(b"\0"):
        if entry:
            meta, name = entry.split(b"\t", 1)
            path = os.fsdecode(name)
            if _product(path):
                files[path] = meta.split()[-1].decode("ascii")
    return files


def _trail_path(root: Path, task_id: str) -> Path:
    return sealed_dir(root, task_id).with_name(task_id + ".trail.jsonl")


def _trail_rows(root: Path, task_id: str) -> list[dict[str, Any]]:
    path = _trail_path(root, task_id)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def record_trail(root: Path, task: dict[str, Any], command: str, view: dict[str, Any] | None = None) -> None:
    """Append only on product changes; never touch the real index or history."""
    from .workspace import product_tree, tree_digest

    tree = Path(task["worktree"])
    digest = product_tree(tree, tree_digest(tree), write=True)
    rows = _trail_rows(root, task["id"])
    if rows and rows[-1]["tree"] == digest:
        return
    changed = []
    for entry in _git(tree, "diff", "--no-renames", "--numstat", "-z", task["source_head"], digest).split(b"\0"):
        if entry:
            added, deleted, name = entry.split(b"\t", 2)
            if _product(os.fsdecode(name)):
                changed.append({"path": os.fsdecode(name), "added": int(added) if added.isdigit() else 0,
                                "deleted": int(deleted) if deleted.isdigit() else 0})
    view = view if view is not None else snapshot(root, task)
    row = {"at": datetime.now(timezone.utc).isoformat(), "command": command, "tree": digest,
           "changed": changed, "out_of_scope": (view or {}).get("out_of_scope", [])}
    path = _trail_path(root, task["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def trajectory(root: Path, task: dict[str, Any], tree: Path, candidate: str) -> dict[str, Any]:
    """Summarize observed content transitions, not line-count coincidences."""
    from .store import load_task_timeline

    rows = _trail_rows(root, task["id"])
    original = product_files(tree, task["source_head"])
    final = product_files(tree, candidate)
    previous = original
    files: dict[str, Any] = {}
    created, outside = set(), set()
    for index, row in enumerate(rows, 1):
        current = product_files(tree, row["tree"])
        touched = {p for p in previous.keys() | current.keys() if previous.get(p) != current.get(p)}
        # A first observation may already equal the base (an unchanged opening snapshot).
        for path in sorted(touched):
            entry = files.setdefault(path, {"rewrites": 0, "first_seen": index})
            entry["rewrites"] += 1
        created.update(current.keys() - original.keys())
        outside.update(row.get("out_of_scope", []))
        previous = current
    span = (datetime.fromisoformat(rows[-1]["at"]) - datetime.fromisoformat(rows[0]["at"])).total_seconds() if rows else 0
    final_changed = {p for p in original.keys() | final.keys() if original.get(p) != final.get(p)}
    return {"snapshots": len(rows), "span_seconds": span, "files": files,
            "created_then_deleted": sorted(created - final.keys()),
            "out_of_scope_seen": sorted(outside - final_changed),
            "stops": sum(step.get("phase") == "site-stopped" for step in load_task_timeline(root, task["id"])["steps"])}


def require_running(task: dict[str, Any]) -> None:
    if task.get("site_stop"):
        raise ChainBroken("site-stopped: 工地已停工；先 handoff，再 backbrief，或者改 draft/ 后 start 并由用户重新 confirm-map")


def _task(root: Path) -> tuple[Path, dict[str, Any]]:
    from .workspace import load_task

    root = real_root(root)
    task = load_task(project_key(root))
    if not task or task.get("process") in {"completed", "abandoned"}:
        raise ChainBroken("site-task-missing: no active ticket")
    return root, task


def stop(root: Path, task: dict[str, Any], kind: str, reason: str, evidence: Any) -> None:
    from .workspace import save_task

    if task.get("site_stop"):
        return
    freeze_worktree(Path(task["worktree"]))
    task["site_stop"] = {"kind": kind, "reason": reason, "evidence": evidence, "at": datetime.now(timezone.utc).isoformat()}
    save_task(project_key(root), task)
    append_task_step(root, task["id"], "site-stopped", kind=kind, reason=reason, evidence=evidence)


def before_command(root: Path, command: str) -> dict[str, Any] | None:
    """Only ready active sites are checked; exemptions never inspect or grant access."""
    if command in EXEMPT or not lookup_project(root):
        return None
    from .workspace import load_task
    from .authorization import require_construction

    root = real_root(root)
    task = load_task(project_key(root))
    if not task or task.get("process") in {"completed", "abandoned"}:
        return None
    if task.get("site_stop"):
        if command in {"verify", "finish"} or command.startswith("worker-"):
            require_running(task)
        return None
    if not task.get("worktree_ready") or task.get("thaw_error"):
        return None
    try:
        require_construction(root, task)
    except ChainBroken:
        return None  # The command's original authorization gate reports its own refusal.
    view = snapshot(root, task)
    if view is None:
        return None
    for reminder in view["reminders"]:
        print(reminder, file=sys.stderr, flush=True)
    if view["out_of_scope"]:
        stop(root, task, "scope", "改动文件超出票面范围或命中禁改清单", view["out_of_scope"])
    elif view["budget"]["ratio"] > 1.5:
        stop(root, task, "budget", "改动量超过预算 150%", view["budget"])
    view["stop"] = task.get("site_stop") or None
    record_trail(root, task, command, view)
    if command in {"verify", "finish"} or command.startswith("worker-"):
        require_running(task)
    return view


def andon(root: Path, reason: str) -> dict[str, Any]:
    if not isinstance(reason, str) or not reason.strip():
        raise ChainBroken("andon-reason-required: 请说明走不通的原因")
    root, task = _task(root)
    from .authorization import require_construction
    if not task.get("site_stop"):
        require_construction(root, task)
    stop(root, task, "andon", reason.strip(), {"reason": reason.strip()})
    return {"site": snapshot(root, task), "readiness": "stopped", "next_action": "handoff"}


def handoff(root: Path) -> dict[str, Any]:
    root, task = _task(root)
    view = snapshot(root, task)
    if view is None:
        raise ChainBroken("site-source-error: ticket package unavailable")
    ticket = (sealed_dir(root, task["id"]) / "ticket.md").read_text(encoding="utf-8")
    verify = task.get("verify") or {}
    evidence = verify.get("stdout") or "尚无当前候选的验货结果"
    spec = json.loads((sealed_dir(root, task["id"]) / "spec.json").read_text(encoding="utf-8"))
    last = "未验货" if not verify else "最近整体验货通过" if verify.get("exit") == 0 else "最近整体验货未通过；单项状态参看输出"
    results = "\n".join(f"- {r['id']}: {r['text']}；{last}" for r in spec["results"])
    files = "\n".join(f"- {'越界' if p in view['out_of_scope'] else '范围内'}: {p}" for p in view["changed"])
    text = (ticket + "\n## 结果与最近检查\n" + results + f"\n验货 exit={verify.get('exit', '未运行')}\n{evidence}\n"
            + "\n## 改动文件\n" + files + "\n## 预算与停工原因\n" + json.dumps(view, ensure_ascii=False, indent=2)
            + "\n\n## 两条出路\n先 backbrief 恢复已有施工授权以撤回越界改动；或者修改 draft/、start 重审，由用户 confirm-map。\n"
            + "\n## 给新会话的提示词\n请读取本简报和封存票包，完整保留目标。复述实际 out_of_scope 清单、至少 20 字的 goal 和非空 next，"
              "写入 JSON 后执行 backbrief --file；不要绕路，解决不了就 andon。恢复后若仍越界，下一次调用会再次停工。\n")
    path = sealed_dir(root, task["id"]).with_name(task["id"] + ".handoff") / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8] + ".md")
    atomic_write(path, text.encode("utf-8"))
    return {"path": str(path), "site": view, "next_action": "backbrief"}


def backbrief(root: Path, brief: Any) -> dict[str, Any]:
    root, task = _task(root)
    view = snapshot(root, task)
    if not task.get("site_stop"):
        raise ChainBroken("site-not-stopped: no stopped site to resume")
    if not isinstance(brief, dict) or view is None:
        raise ChainBroken("backbrief-mismatch: expected a JSON object and current site facts")
    outside, goal, next_step = brief.get("out_of_scope"), brief.get("goal"), brief.get("next")
    if (not isinstance(outside, list) or any(not isinstance(p, str) for p in outside)
            or sorted(outside) != view["out_of_scope"] or not isinstance(goal, str) or len(goal.strip()) < 20
            or not isinstance(next_step, str) or not next_step.strip()):
        raise ChainBroken("backbrief-mismatch: out_of_scope 必须与现场完全一致，goal 至少 20 字，next 不能为空")
    from .presence import require_authorization
    from .authorization import validate_ticket
    from .workspace import save_task

    require_authorization(root, task)
    validate_ticket(root, task)
    try:
        thaw_worktree(Path(task["worktree"]))
        append_task_step(root, task["id"], "site-resumed", backbrief=brief)
        task.pop("site_stop")
        save_task(project_key(root), task)
    except (OSError, ChainBroken):
        freeze_worktree(Path(task["worktree"]))
        raise
    return {"site": snapshot(root, task), "readiness": "ready", "next_action": "implement-and-verify"}


def confirmed(root: Path, task: dict[str, Any]) -> None:
    """Clear a stop only after human confirmation and full activation succeeded."""
    if not task.get("site_stop"):
        return
    from .workspace import save_task

    previous = task.pop("site_stop")
    try:
        save_task(project_key(root), task)
    except (OSError, ChainBroken):
        task["site_stop"] = previous
        freeze_worktree(Path(task["worktree"]))
        raise
