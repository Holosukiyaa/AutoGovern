"""Where the code has a problem, and where to look when blaming."""
from __future__ import annotations

from pathlib import Path
from typing import Any

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
