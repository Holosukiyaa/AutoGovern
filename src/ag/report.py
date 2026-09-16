"""Where the code has a problem, and where to look when blaming."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .checkup import checkup
from .managed import project_snapshot
from .queue import runs_path


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
    }
