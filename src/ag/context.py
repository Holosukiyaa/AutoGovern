"""T9a observation only: review usage/size (r1-r2), burden and trend (r3-r5)."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

_review = ContextVar("ag_review_observation", default=None)


def observe_review(function):
    """r1-r2: isolate one review, including retries, from other CLI/MCP calls."""
    @wraps(function)
    def run(*args, **kwargs):
        token = _review.set({"calls": [], "sent": 0, "raw": 0, "omitted": 0, "truncated": set()})
        try:
            return function(*args, **kwargs)
        finally:
            _review.reset(token)
    return run


def normalize_usage(value):
    """r1: malformed/missing provider observations are null, never verdict errors."""
    if not isinstance(value, dict):
        return None
    result = {key: value.get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
    details = value.get("prompt_tokens_details")
    cached = details.get("cached_tokens") if isinstance(details, dict) else None
    result["cached_tokens"] = cached if cached is not None else value.get("prompt_cache_hit_tokens")
    if any(type(v) is not int or v < 0 for v in list(result.values())[:3]):
        return None
    if result["cached_tokens"] is not None and (type(result["cached_tokens"]) is not int or result["cached_tokens"] < 0):
        return None
    return result


def record_call(messages, usage):
    """r1-r2: retain each attempt and actual system/user message character counts."""
    state = _review.get()
    if state is not None:
        sent = sum(len(m.get("content", "")) for m in messages if m.get("role") in {"system", "user"})
        state["calls"].append(normalize_usage(usage))
        state["sent"] += sent
        state["raw"] += sent + state["omitted"]


def review_measurement():
    """r1-r2: return stable payload fields for both history and the review receipt."""
    state = _review.get()
    if state is None:
        return {"usage": None, "exam_size": None}
    calls = state["calls"]
    valid = [call for call in calls if call is not None]
    usage = None
    if valid:
        usage = {key: sum(call[key] or 0 for call in valid) if any(call[key] is not None for call in valid) else None
                 for key in valid[0]}
        usage.update(calls=len(calls), per_call=list(calls))
    return {"usage": usage, "exam_size": {"sent_chars": state["sent"], "raw_chars": state["raw"],
                                          "truncated_files": len(state["truncated"])}}


def observe_pack(packed, tree, full_diff):
    """r2: measure omitted originals without changing any sent pack/truncation rule."""
    state = _review.get()
    if state is None:
        return
    for group in ("changed_files", "this_ticket_checks"):
        for item in packed.get(group, []):
            if not (item.get("truncated") or item.get("slimmed")):
                continue
            try:
                original = (tree / item["path"]).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            shown = item.get("content", "")
            extra = len(json.dumps(original, ensure_ascii=False)) - len(json.dumps(shown, ensure_ascii=False))
            state["omitted"] += max(0, extra)
            state["truncated"].add(item["path"])
    shown_diff = packed.get("annotated_diff", "")
    state["omitted"] += max(0, len(json.dumps(full_diff, ensure_ascii=False)) - len(json.dumps(shown_diff, ensure_ascii=False)))
    if len(full_diff) > len(shown_diff):
        state["truncated"].update(m[1] for m in re.finditer(r"(?m)^(.+?):\d+ \|[^\n]*", full_diff) if m.end() > len(shown_diff))


def _git(tree, *args):
    """r3-r4: read Git paths/blobs without refreshing the real index."""
    return subprocess.check_output(["git", "--no-optional-locks", "-C", str(tree), *args])


def direct_neighbors(project, tree, entries, known, source_head):
    """r3-r4: reuse T8 adapter extraction on exact source text, without live checkout reads."""
    from .critic import neighbors
    from .structure import load_adapter, _extract_refs, _resolve_ref

    adapter = load_adapter(project)
    configs = list(adapter.get("adapters", {}).values()) if adapter.get("multi") else [adapter.get("config")]
    configs = [cfg for cfg in configs if isinstance(cfg, dict)]
    if not configs:
        return set(neighbors(tree, entries, known=known if source_head else None))
    found = set()
    with tempfile.TemporaryDirectory(prefix="ag-context-") as scratch:
        snapshot = Path(scratch)
        for item in entries:
            path = snapshot / item["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(item["content"], encoding="utf-8")
        for cfg in configs:
            try:
                patterns = [re.compile(str(p)) for p in cfg.get("ref_patterns", [])]
            except re.error:
                continue
            for item in entries:
                if Path(item["path"]).suffix.lower() not in cfg.get("source_exts", []):
                    continue
                refs, _ = _extract_refs(snapshot, item["path"], patterns)
                for ref in refs:
                    target = _resolve_ref(snapshot, item["path"], ref, known)
                    if target and target != item["path"]:
                        found.add(target)
    return found


def burden(tree, scope, *, source_head="", paths=None, project=None):
    """r3-r4: count scope plus one-hop neighbors, with the exam's reference rules."""
    from .site import matches

    if source_head:
        names = _git(tree, "ls-tree", "-rz", "--name-only", source_head)
    else:
        names = _git(tree, "ls-files", "-c", "-o", "--exclude-standard", "-z")
    known = {p.decode("utf-8", "replace") for p in names.split(b"\0") if p}
    selected = set(paths) & known if paths is not None else {
        p for p in known if any(matches(p, g) for g in scope.get("allow", []))
        and not any(matches(p, g) for g in scope.get("deny", []))}
    selected = {p for p in selected if p != ".ag-check" and not p.startswith(".ag-check/")}

    def text(path):
        if source_head:
            return _git(tree, "show", f"{source_head}:{path}").decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
        try:
            return (tree / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    entries = [{"path": p, "content": text(p)} for p in sorted(selected)]
    direct = (direct_neighbors(project or tree, tree, entries, known, source_head) & known) - selected
    direct = {p for p in direct if not p.startswith(".ag-check/")}
    scope_chars = sum(len(item["content"]) for item in entries)
    neighbor_chars = sum(len(text(p)) for p in direct)
    total = scope_chars + neighbor_chars
    return {"scope_files": len(selected), "scope_chars": scope_chars, "neighbor_files": len(direct),
            "neighbor_chars": neighbor_chars, "total_chars": total, "est_tokens": (total + 3) // 4}


def task_burden(root, task):
    """r3: preserve the opening observation; older active tickets can derive it read-only."""
    if task.get("context_burden") is not None:
        return task["context_burden"]
    if task.get("package_spec") and task.get("source_head"):
        return burden(root, task["package_spec"]["scope"], source_head=task["source_head"])
    return None


def actual_burden(task, root=None):
    """r4: recompute against actual tracked and untracked changes, never porcelain."""
    tree = Path(task["worktree"])
    names = _git(tree, "diff", "--name-only", "-z", task["source_head"]) + _git(tree, "ls-files", "-o", "--exclude-standard", "-z")
    paths = {p.decode("utf-8", "replace") for p in names.split(b"\0") if p}
    return burden(tree, {}, paths=paths, project=root)


def comparison(root, task, switch=None):
    """r4: one output shape even when local checks prevent a model call."""
    switch = switch or {}
    return {"estimate": task_burden(root, task),
            "measured": {"exam_size": switch.get("exam_size"), "usage": switch.get("usage")},
            "actual_scope": actual_burden(task, root)}


def trend(root):
    """r5: newest ten review events, including nulls from older history."""
    from .store import list_llm_events

    result = []
    for row in reversed(list_llm_events(root, "switch_event", limit=10)):
        estimate = row.get("context_burden") if isinstance(row.get("context_burden"), dict) else {}
        size = row.get("exam_size") if isinstance(row.get("exam_size"), dict) else {}
        usage = row.get("usage") if isinstance(row.get("usage"), dict) else {}
        result.append({"task_id": row.get("task_id"), "estimate_chars": estimate.get("total_chars"),
                       "raw_chars": size.get("raw_chars"), "prompt_tokens": usage.get("prompt_tokens")})
    return result
