"""Where the code has a problem, and where to look when blaming."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .checkup import SKIP_PARTS, checkup, _skip
from .managed import project_snapshot
from .queue import runs_path

MAX_TREE_FILES = 5000


def _probe_paths(item: dict[str, Any]) -> list[str]:
    paths = []
    if item.get("path"):
        paths.append(str(item.get("path")).replace("\\", "/"))
    for rel in item.get("paths") or []:
        paths.append(str(rel).replace("\\", "/"))
    return [p for p in paths if p]


def file_index(root: Path, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    root = root.expanduser().resolve()
    by_path: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        for rel in _probe_paths(item):
            by_path.setdefault(rel, []).append(item)
    rows: list[dict[str, Any]] = []
    count = 0
    for path in sorted(root.rglob("*")):
        if _skip(path) or not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        probes = []
        for item in by_path.get(rel, []):
            speech = item.get("speech") if isinstance(item.get("speech"), dict) else {}
            probes.append(
                {
                    "id": item.get("id"),
                    "kind": item.get("kind"),
                    "status": _status_label(item),
                    "claim": speech.get("claim"),
                    "breadth": speech.get("breadth"),
                    "note": item.get("note"),
                }
            )
        rows.append({"path": rel, "probes": probes, "probed": bool(probes)})
        count += 1
        if count >= MAX_TREE_FILES:
            break
    return rows


def problems(root: Path) -> dict[str, Any]:
    snap = project_snapshot(root)
    last = snap.get("last_run") if isinstance(snap.get("last_run"), dict) else {}
    evidence = str(runs_path(root.resolve()))
    rows: list[dict[str, Any]] = []
    if snap.get("stale"):
        rows.append(
            {
                "kind": "stale",
                "path": "",
                "problem": "证据过期：当前 HEAD 与上次 git_head 不一致，旧绿不能当现在的",
                "speech": "whole tree",
                "blame": {
                    "evidence": evidence,
                    "run_id": last.get("run_id"),
                    "git_head": last.get("git_head"),
                    "current_head": snap.get("git_head"),
                },
            }
        )
    for item in snap.get("items") or []:
        path = str(item.get("path") or "")
        claim = str((item.get("speech") or {}).get("claim") or item.get("note") or "")
        loc = {
            "evidence": evidence,
            "run_id": last.get("run_id"),
            "git_head": last.get("git_head"),
            "probe_id": item.get("id"),
        }
        if item.get("unverifiable"):
            rows.append(
                {
                    "kind": "unknown",
                    "path": path or str(item.get("scope") or ""),
                    "problem": claim or "无法验证",
                    "speech": "wide",
                    "blame": loc,
                }
            )
        elif item.get("skipped"):
            rows.append(
                {
                    "kind": "skipped",
                    "path": path,
                    "problem": f"{claim or path} 未跑，不能当绿",
                    "speech": (item.get("speech") or {}).get("breadth"),
                    "blame": loc,
                }
            )
        elif not item.get("trusted") and item.get("green_ok") is False:
            rows.append(
                {
                    "kind": "barred",
                    "path": path,
                    "problem": f"{claim} 红了",
                    "speech": (item.get("speech") or {}).get("breadth"),
                    "blame": loc,
                }
            )
    return {
        "schema": "ag.report.v1",
        "root": snap["root"],
        "trust_rate": snap.get("trust_rate"),
        "reminder": "trust_rate does not say which file is wrong; see problems[].path and problems[].blame",
        "problems": rows,
        "declared": snap.get("declared"),
    }


def _status_label(item: dict[str, Any]) -> str:
    if item.get("unverifiable") or item.get("kind") == "unknown":
        return "无法验证"
    if item.get("skipped"):
        return "未跑"
    if item.get("trusted"):
        return "绿"
    if item.get("green_ok") is False:
        return "红"
    return "无记录"


def dashboard_view(root: Path) -> dict[str, Any]:
    snap = project_snapshot(root)
    issue = problems(root)
    advice = checkup(root, insert=False)
    last = snap.get("last_run") if isinstance(snap.get("last_run"), dict) else {}
    evidence = str(runs_path(root.resolve()))
    actions: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    tree: list[dict[str, Any]] = []
    for item in snap.get("items") or []:
        speech = item.get("speech") if isinstance(item.get("speech"), dict) else {}
        status = _status_label(item)
        node = {
            "id": item.get("id"),
            "kind": item.get("kind"),
            "path": item.get("path") or "",
            "note": item.get("note") or "",
            "breadth": speech.get("breadth"),
            "claim": speech.get("claim"),
            "status": status,
            "run_id": last.get("run_id"),
            "git_head": last.get("git_head"),
            "evidence": evidence,
        }
        tree.append(node)
        text = f"{node['path'] or node['note'] or node['id']}：{node['claim'] or ''} · {status}"
        row = {"id": node["id"], "text": text, "severity": "ok", "path": node["path"]}
        if item.get("unverifiable"):
            row["severity"] = "warn"
            records.append(row)
        elif item.get("skipped"):
            row["severity"] = "warn"
            alerts.append(row)
        elif item.get("trusted"):
            records.append(row)
        elif item.get("green_ok") is False:
            row["severity"] = "error"
            actions.append(row)
    if snap.get("stale"):
        actions.insert(
            0,
            {
                "id": "",
                "severity": "error",
                "text": "证据过期：当前 HEAD 与上次 git_head 不一致",
                "path": "",
            },
        )
    for hint in advice.get("suggestions") or []:
        alerts.append(
            {
                "id": "",
                "severity": "warn",
                "text": str(hint.get("claim") or hint.get("path") or ""),
                "path": hint.get("path") or "",
            }
        )
    files = file_index(root, snap.get("items") or [])
    green_n = sum(1 for item in snap.get("items") or [] if item.get("trusted"))
    red_n = sum(1 for item in snap.get("items") or [] if item.get("green_ok") is False)
    unknown_n = sum(1 for item in snap.get("items") or [] if item.get("unverifiable"))
    advice_lines = ["总体建议（给人和 AI，不是验证、不拦业务）："]
    for item in snap.get("items") or []:
        if item.get("unverifiable"):
            advice_lines.append("- 无法验证：" + str(item.get("note") or ""))
    for hint in advice.get("suggestions") or []:
        advice_lines.append("- " + str(hint.get("claim") or hint.get("path") or ""))
    if len(advice_lines) == 1:
        advice_lines.append("- 声明过的针里没有额外建议。")
    return {
        "root": snap["root"],
        "trust_rate": snap.get("trust_rate"),
        "stale": snap.get("stale"),
        "declared": snap.get("declared"),
        "actions": actions,
        "alerts": alerts,
        "records": records,
        "tree": tree,
        "evidence_text": (
            f"run {last.get('run_id') or '-'} git {last.get('git_head') or '(无 git)'} "
            f"{evidence}"
        ),
        "problems": issue.get("problems"),
        "files": files,
        "stats": {
            "green": green_n,
            "red": red_n,
            "unknown": unknown_n,
            "unprobed": sum(1 for row in files if not row.get("probed")),
        },
        "advice": advice_lines,
    }
