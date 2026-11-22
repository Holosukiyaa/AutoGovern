"""T9b r1/r3-r5: entropy evidence and history references; never delivery gates."""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

from .advice import _classify_shortcut, _is_non_prod_path, _SUPPRESS_RE
from .diffparse import parse
from .history import read_records
from .site import _git, product_files, snapshot
from .store import list_llm_events


def line_counts(tree, source, candidate):
    """r1/r5: product numstat for a pair of immutable Git trees, including binary/renames."""
    added = deleted = 0
    stats = iter(_git(tree, "diff", "--numstat", "-z", source, candidate).split(b"\0"))
    for entry in stats:
        if not entry:
            continue
        a, d, name = entry.split(b"\t", 2)
        if not name:
            next(stats)
            name = next(stats)
        path = os.fsdecode(name)
        if path == ".ag-check" or path.startswith(".ag-check/"):
            continue
        added += int(a) if a.isdigit() else 0
        deleted += int(d) if d.isdigit() else 0
    return {"added": added, "deleted": deleted, "net": added - deleted}


def python_tree(tree, revision, path):
    """r1: parse candidate/base definitions without making invalid code a new gate."""
    text = _git(tree, "show", f"{revision}:{path}").decode("utf-8", "replace")
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError):
        return ast.Module(body=[], type_ignores=[])


def parallel_base(name):
    """r1: names suggesting a parallel implementation, not duplicate-code detection."""
    match = re.fullmatch(r"(.+?)(?:_v\d+|_new|_old|_copy|(?<=[A-Za-z_])\d+)", name)
    return match[1] if match else None


def ledger(tree, source, candidate):
    """r1: one deterministic product-only ledger for exam, receipt and history."""
    original = product_files(tree, source)
    current = product_files(tree, candidate)
    new = sorted(current.keys() - original.keys())
    changed = {p for p in current if current[p] != original.get(p)}
    shortcuts, broad, parallel, same = [], [], [], []
    suppress_added = suppress_removed = 0
    added_lines = {}
    previous = ""
    diff = _git(tree, "-c", "core.quotePath=false", "diff", "-U0", source, candidate).decode("utf-8", "replace")
    for line in parse(diff):
        if line.kind in {"file", "hunk", "context"}:
            previous = ""
        if line.path == ".ag-check" or line.path.startswith(".ag-check/"):
            continue
        if line.kind == "add":
            text = line.raw[1:]
            added_lines.setdefault(line.path, set()).add(line.new)
            suppress_added += len(_SUPPRESS_RE.findall(text))
            if not _is_non_prod_path(line.path):
                kind = _classify_shortcut(text, previous)
                if kind:
                    shortcuts.append({"file": line.path, "line": line.new, "kind": kind})
            previous = text
        elif line.kind == "delete":
            suppress_removed += len(_SUPPRESS_RE.findall(line.raw[1:]))
    old_symbols, new_symbols = {}, {}
    for path in sorted(original):
        if path.endswith(".py"):
            old_symbols[path] = {node.name for node in python_tree(tree, source, path).body
                                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    for path in sorted(changed):
        if not path.endswith(".py"):
            continue
        module = python_tree(tree, candidate, path)
        new_symbols[path] = [node for node in module.body
                             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        for node in ast.walk(module):
            if isinstance(node, ast.ExceptHandler) and node.lineno in added_lines.get(path, set()):
                if node.type is None or isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}:
                    broad.append({"file": path, "line": node.lineno})
    names = set().union(*old_symbols.values()) if old_symbols else set()
    names.update(node.name for nodes in new_symbols.values() for node in nodes)
    for path, nodes in new_symbols.items():
        for node in nodes:
            base = parallel_base(node.name)
            if node.name not in old_symbols.get(path, set()) and base in names:
                parallel.append({"file": path, "line": node.lineno, "new": node.name, "existing": base})
    existing = sorted(original.keys() & current.keys())
    for path in new:
        name = Path(path).name
        clash = next((p for p in existing if Path(p).name == name), None)
        if clash:
            same.append({"new": path, "existing": clash})
        base = parallel_base(Path(path).stem)
        origin = next((p for p in current if Path(p).stem == base and Path(p).suffix == Path(path).suffix), None)
        if origin:
            parallel.append({"new": path, "existing": origin})
    return {"lines": line_counts(tree, source, candidate), "new_files": len(new),
            "shortcuts": {"count": len(shortcuts), "items": shortcuts[:10]},
            "suppressions": {"added": suppress_added, "removed": suppress_removed, "delta": suppress_added - suppress_removed},
            "broad_excepts": {"count": len(broad), "items": broad[:10]},
            "parallel_impls": {"count": len(parallel), "items": parallel[:10]},
            "same_name_files": {"count": len(same), "items": same[:10]}}


def observations(root, task, candidate):
    """r1/r4: bind one ledger and the authoritative T7 budget to the candidate."""
    view = snapshot(root, task)
    actual = view["budget"] if view else None
    budget = task.get("package_spec", {}).get("budget")
    budget_actual = {"budget": budget, "actual": {k: actual[k] for k in ("files", "lines")},
                     "ratio": actual["ratio"]} if actual else None
    return {"entropy": ledger(Path(task["worktree"]), task["source_head"], candidate),
            "budget_actual": budget_actual, "kind": task.get("package_spec", {}).get("kind")}


def status_observations(root):
    """r3-r4: recent review entropy and latest-per-ticket budget, null for old rows."""
    rows = list_llm_events(root, "switch_event", limit=0)
    trend, reference, seen = [], [], set()
    for row in reversed(rows):
        entropy = row.get("entropy") or {}
        if len(trend) < 10:
            trend.append({"task_id": row.get("task_id"), "net_lines": (entropy.get("lines") or {}).get("net"),
                          "new_files": entropy.get("new_files"),
                          **{k: (entropy.get(k) or {}).get("count") for k in ("shortcuts", "broad_excepts", "parallel_impls", "same_name_files")},
                          "suppressions_delta": (entropy.get("suppressions") or {}).get("delta")})
        task_id = row.get("task_id")
        if task_id and task_id not in seen and len(reference) < 10:
            seen.add(task_id)
            usage = row.get("budget_actual") or {}
            budget, actual = usage.get("budget") or {}, usage.get("actual") or {}
            reference.append({"task_id": task_id, "kind": row.get("kind"), "budget_files": budget.get("files"),
                              "budget_lines": budget.get("lines"), "actual_files": actual.get("files"),
                              "actual_lines": actual.get("lines"), "ratio": usage.get("ratio")})
        if len(trend) == 10 and len(reference) == 10:
            break
    return {"entropy_trend": trend, "budget_reference": reference, "slim_reminder": slim_reminder(root)}


def slim_reminder(root):
    """r5: only successful package-ticket finishes count; a slim finish resets both sums."""
    finished = {}
    for row in read_records(root, kind="task-step"):
        payload = row["payload"]
        if payload.get("phase") == "finish" and (payload.get("task") or {}).get("package_spec"):
            finished.pop(row["task_id"], None)
            finished[row["task_id"]] = payload
    since, tickets, net, start = None, 0, 0, 0
    entries = list(finished.items())
    for index, (task_id, payload) in enumerate(entries):
        if payload["task"]["package_spec"].get("kind") == "slim":
            since, start = task_id, index + 1
    for task_id, payload in entries[start:]:
        task = payload["task"]
        tickets += 1
        if task.get("source_head") and payload.get("head"):
            net += line_counts(root, task["source_head"], payload["head"])["net"]
    due = tickets >= 8 or net >= 800
    return {"due": due, "tickets": tickets, "net_lines": net, "since": since,
            "threshold": {"tickets": 8, "net_lines": 800}, "message": "下一张宜开减重票" if due else ""}
