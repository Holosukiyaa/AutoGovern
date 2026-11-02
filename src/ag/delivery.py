"""Read-only delivery facts. Views never grant construction or merge authority."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .history import digest, read_records
from .managed import ChainBroken, lookup_project, project_key, real_root
from .store import list_llm_events, load_task_timeline, project_dir, scan_llm_log
from .ticket_doc import section_lines, split_document

PASS = {"passed", "pass", "allow"}


def intent_identity(task: dict[str, Any], text: str, sealed_redlines: str) -> str:
    intent, redlines = split_document(text)
    return digest({"task_id": task.get("id"), "source_head": task.get("source_head"), "worktree": task.get("worktree"), "intent": intent, "redlines": section_lines(redlines), "sealed_redlines": sealed_redlines, "fixed": task.get("fixed") or [], "anchors": task.get("anchors") or [], "goal_link": task.get("goal_link")})


def task_facts(task: dict[str, Any]) -> dict[str, Any]:
    names = ("id", "branch", "source_head", "worktree", "portrait", "anchors", "fixed", "fixed_rules", "redlines", "anchor_preview", "intent_identity", "intent_map_confirmed", "authorization_identity", "worktree_ready", "thaw_error", "ticket_review", "verify", "verified_tree", "goal_link", "check_argv", "process", "cleanup_error", "archive_error", "merged_head")
    return {name: task[name] for name in names if name in task}


def task_reviews(root: Path, task_id: str, *, diagnostics: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    rows = []
    seen = {}
    for table in ("ticket_event", "switch_event", "critic_event"):
        scan = scan_llm_log(root, table)
        if scan["bad_lines"]:
            raise ChainBroken(f"history-source-error: malformed review log: {scan['path']}")
        if diagnostics is not None:
            diagnostics.extend(item for item in scan["diagnostics"] if task_id in {item.get("task_id"), item.get("expected_task_id")})
        for event in scan["rows"]:
            if event.get("task_id") != task_id:
                continue
            identity = str(event.get("report_id") or "")
            if not identity:
                continue
            if identity in seen:
                if any(seen[identity].get(name) != event.get(name) for name in ("task_id", "outcome", "candidate")):
                    raise ChainBroken(f"history-identity-conflict: compatible report {identity}")
                continue
            seen[identity] = event
            rows.append({**event, "seat": table.removesuffix("_event"), "ref": scan["refs"].get(identity) or f"{scan['path']}#{identity}"})
    return sorted(rows, key=lambda row: (str(row.get("ts") or ""), str(row.get("report_id") or "")))


def _read_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ChainBroken(f"history-source-error: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ChainBroken(f"history-source-error: expected object: {path}")
    return value


def _candidate_current(root: Path, task: dict[str, Any], verify: dict[str, Any]) -> bool:
    candidate = str(verify.get("candidate") or "")
    tree = Path(str(task.get("worktree") or ""))
    if not candidate or not tree.is_dir():
        return False
    diff = subprocess.run(["git", "-C", str(tree), "diff", "--quiet", candidate, "--"], capture_output=True)
    if diff.returncode not in {0, 1}:
        raise ChainBroken("history-source-error: verification candidate is unavailable")
    if diff.returncode:
        return False
    untracked = subprocess.run(["git", "-C", str(tree), "ls-files", "--others", "--exclude-standard", "-z"], capture_output=True)
    if untracked.returncode:
        raise ChainBroken("history-source-error: cannot read candidate working state")
    if untracked.stdout:
        return False
    if verify.get("check_selection"):
        from .checks import selection

        enrolled = (lookup_project(root) or {}).get("test_argv") or []
        if selection(tree, list(enrolled))["sha256"] != verify["check_selection"].get("sha256"):
            return False
    return True


def build_delivery_snapshot(root: Path, task_id: str = "") -> dict[str, Any]:
    root = real_root(root)
    base = project_dir(root)
    active = _read_object(base / "task.json")
    requested = str(task_id or active.get("id") or "").strip()
    if requested and not re.fullmatch(r"[A-Za-z0-9_-]+", requested):
        return {"schema": "ag.delivery.v1", "root": str(root), "task_id": requested, "found": False, "error": "task-not-found", "readiness": "task-not-found", "next_action": "check-task-id"}
    if not requested:
        return {"schema": "ag.delivery.v1", "root": str(root), "task_id": "", "found": False, "readiness": "idle", "next_action": "write-ticket"}
    records = read_records(root, task_id=requested)
    timeline = load_task_timeline(root, requested)
    steps = timeline["steps"]
    diagnostics = list(timeline.get("diagnostics") or [])
    valid_records = []
    for row in records:
        if row["payload"].get("task_id", requested) != requested:
            diagnostics.append({"kind": "wrong-task", "source": row["_source"], "identity": row["id"]})
        else:
            valid_records.append(row)
    records = valid_records
    valid_steps = []
    for step in steps:
        if step.get("task_id", requested) != requested:
            diagnostics.append({"kind": "wrong-task", "source": timeline["path"], "phase": step.get("phase")})
        else:
            valid_steps.append(step)
    steps = valid_steps
    task = {}
    for step in steps:
        candidate_task = step.get("task")
        if isinstance(candidate_task, dict):
            if candidate_task.get("id") == requested:
                task = dict(candidate_task)
            else:
                diagnostics.append({"kind": "wrong-task", "source": timeline["path"], "phase": step.get("phase")})
    is_active = active.get("id") == requested
    if is_active:
        task = active
    texts = [row["payload"].get("text", "") for row in records if row["kind"] == "ticket"]
    ticket_file = base / "tickets" / f"{requested}.md"
    if ticket_file.is_file():
        texts.append(ticket_file.read_text(encoding="utf-8"))
    texts.sort(key=lambda value: next((line.removeprefix("updated: ") for line in str(value).splitlines() if line.startswith("updated: ")), ""))
    text = str(task.get("anchor_preview") or (texts[-1] if texts else ""))
    session = _read_object(base / "knowledge" / "sessions" / f"{requested}.json")
    archived_sessions = [row["payload"] for row in records if row["kind"] == "session"]
    if not session and archived_sessions:
        session = archived_sessions[-1]
    if session and session.get("task_id") != requested:
        diagnostics.append({"kind": "wrong-task", "source": str(base / "knowledge" / "sessions")})
        session = {}
    reviews = task_reviews(root, requested, diagnostics=diagnostics)
    if not task and not timeline.get("found") and not texts and not session and not reviews:
        return {"schema": "ag.delivery.v1", "root": str(root), "task_id": requested, "found": False, "error": "task-not-found", "readiness": "task-not-found", "next_action": "check-task-id", "diagnostics": diagnostics}
    intent, red_body = split_document(text)
    fixed = list(task.get("fixed") or [])
    if not fixed and intent.strip():
        fixed = [intent.strip()]
    goal = {"text": intent, "fixed": fixed, "sha256": digest({"intent": intent, "fixed": fixed}), "confirmed": bool(task.get("intent_map_confirmed")) or any(step.get("phase") == "intent-map-confirmed" for step in steps)}
    goal_link = task.get("goal_link") or next((step.get("goal_link") for step in reversed(steps) if step.get("goal_link")), None)
    process = str(task.get("process") or session.get("process") or "active")
    terminal = next((step for step in reversed(steps) if step.get("phase") in {"finish", "abandon"}), {})
    if terminal:
        process = "completed" if terminal["phase"] == "finish" else "abandoned"
    verify = task.get("verify") if isinstance(task.get("verify"), dict) else {}
    if not verify:
        verify = next((step["verify"] for step in reversed(steps) if isinstance(step.get("verify"), dict)), {})
    if verify and verify.get("task_id", requested) != requested:
        diagnostics.append({"kind": "wrong-task", "source": "verify", "task_id": verify.get("task_id")})
        verify = {}
    blockers = []
    advisories = []
    def issue(kind, evidence, action, **extra):
        return {"kind": kind, "evidence": evidence, "next_action": action, **extra}
    by_report = {row["report_id"]: row for row in reviews}
    review = task.get("ticket_review") if isinstance(task.get("ticket_review"), dict) else {}
    if not review:
        review = next((row for row in reversed(reviews) if row["seat"] == "ticket"), {})
    if review.get("configured") and review.get("outcome") not in PASS:
        blockers.append(issue("ticket-review-rejected", review.get("report_id") or review.get("reason"), "revise-ticket-and-start", items=review.get("items") or [], doubts=review.get("doubts") or []))
    for warning in (review.get("script_digest") or {}).get("warnings") or []:
        advisories.append(issue("ticket-advice", warning, "inspect-evidence"))
    for doubt in review.get("doubts") or []:
        advisories.append(issue("review-question", {"report_id": review.get("report_id"), "question": doubt}, "inspect-evidence"))
    candidate = str(verify.get("candidate") or "")
    switch = verify.get("switch") if isinstance(verify.get("switch"), dict) else {}
    report = by_report.get(str(switch.get("report_id") or ""))
    if switch.get("report_id") and not report:
        for table in ("switch_event", "critic_event"):
            foreign = list_llm_events(root, table, limit=0, report_id=switch["report_id"])
            if any(row.get("task_id") != requested for row in foreign):
                diagnostics.append({"kind": "wrong-task", "source": "verify.switch", "report_id": switch["report_id"]})
    evidence_bound = bool(candidate and report and report.get("candidate") == candidate and report.get("task_id") == requested and report.get("outcome") == switch.get("outcome"))
    for current_review in (review, report or {}):
        for item in current_review.get("items") or []:
            if isinstance(item, dict) and str(item.get("status") or "").casefold() in {"warn", "warning", "advice", "suggestion"}:
                advisories.append(issue("review-advice", {"report_id": current_review.get("report_id"), "item": item}, "inspect-evidence"))
    verified = []
    candidate_current = False
    if evidence_bound and process == "active" and is_active:
        candidate_current = _candidate_current(root, task, verify)
    elif evidence_bound and process == "completed":
        merged_head = str(terminal.get("head") or task.get("merged_head") or "")
        if merged_head and task.get("verified_tree") == candidate:
            merged = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", merged_head + "^{tree}"], capture_output=True, text=True)
            if merged.returncode:
                raise ChainBroken("history-source-error: completed candidate commit is unavailable")
            candidate_current = merged.stdout.strip() == candidate
    verified_ok = bool(verify and verify.get("exit") == 0 and not verify.get("undeclared") and not verify.get("probe_red") and switch.get("outcome") in PASS and evidence_bound and candidate_current)
    if verified_ok:
        verified = [{"result": outcome, "report_id": switch.get("report_id"), "candidate": candidate, "checks": verify.get("check_argv") or [], "source": report["ref"]} for outcome in fixed]
    elif verify:
        if verify.get("exit") != 0:
            blockers.append(issue("checks-failed", verify.get("stderr") or verify.get("refused") or verify.get("exit"), "fix-and-verify"))
        if verify.get("probe_red"):
            blockers.append(issue("probe-red", verify["probe_red"], "repair-behavior-and-verify"))
        if switch.get("configured") and switch.get("outcome") not in PASS:
            blockers.append(issue("switch-rejected" if switch.get("outcome") == "rejected" else "review-unavailable", switch.get("report_id") or switch.get("reason"), "fix-and-verify", items=(report or {}).get("items") or []))
        if switch.get("outcome") in PASS and not evidence_bound:
            blockers.append(issue("missing-evidence", switch.get("report_id"), "verify-current-candidate"))
        if evidence_bound and not candidate_current:
            blockers.append(issue("candidate-changed", candidate, "verify-current-candidate"))
    for probe in verify.get("probes") or []:
        if probe.get("verdict") == "unproven":
            advisories.append(issue("probe-unproven", probe.get("id"), "calibrate-probe"))
    config_error = ""
    try:
        from .critic import load_config

        configuration = load_config(root, read_only=True)
        config_error = str(configuration.get("error") or "")
    except (OSError, ValueError, TypeError, ChainBroken) as exc:
        config_error = str(exc)
    if config_error:
        blockers.append(issue("config-error", config_error, "repair-config"))
    for row in reviews:
        current = row.get("report_id") in {review.get("report_id"), switch.get("report_id")}
        if not current and row.get("outcome") not in PASS:
            advisories.append(issue("historical-review", row["ref"], "retain-original-conclusion", outcome=row.get("outcome"), items=row.get("items") or []))
    requires_decision = any(step.get("phase") == "delivery-change" and step.get("requires_decision") for step in steps)
    identity_changed = False
    if is_active and text:
        live = base / "ticket.md"
        sealed = base / "redlines.copy"
        if not live.is_file() or not sealed.is_file():
            identity_changed = True
        else:
            expected = task.get("intent_identity") or intent_identity(task, text, "\n".join(task.get("redlines") or []) + ("\n" if task.get("redlines") else ""))
            identity_changed = intent_identity(task, live.read_text(encoding="utf-8"), sealed.read_text(encoding="utf-8")) != expected
    if identity_changed:
        blockers.append(issue("intent-identity-changed", str(base / "ticket.md"), "await-user-decision"))
    approved = goal["confirmed"]
    ready = approved and process == "active" and bool(task.get("worktree_ready")) and not task.get("thaw_error") and not identity_changed
    readiness = "ready" if ready else "thaw-failed" if task.get("thaw_error") else "approved-but-frozen" if approved else "await-confirmation"
    if requires_decision or identity_changed:
        action = "await-user-decision"
    elif task.get("cleanup_error"):
        readiness, action = "cleanup-pending", "retry-cleanup"
        blockers.append(issue("cleanup-pending", task["cleanup_error"], action))
    elif task.get("archive_error"):
        readiness, action = "history-close-pending", "retry-history-close"
        blockers.append(issue("history-close-pending", task["archive_error"], action))
    elif process in {"completed", "abandoned"}:
        readiness, action = process, process
    elif any(row["kind"] == "ticket-review-rejected" for row in blockers):
        action = "revise-ticket-and-start"
    elif config_error:
        readiness, action = "config-error", "repair-config"
    elif not approved:
        action = "user-confirm-map"
    elif not ready:
        action = "recover-thaw"
    elif blockers:
        action = blockers[0]["next_action"]
    elif verified_ok:
        action = "finish"
    else:
        action = "implement-and-verify"
    return {
        "schema": "ag.delivery.v1",
        "root": str(root),
        "task_id": requested,
        "found": True,
        "active": is_active,
        "process": process,
        "goal": goal,
        "goal_link": goal_link,
        "contribution": (goal_link or {}).get("contribution") or task.get("portrait") or "",
        "progress": {
            "verified": verified,
            "attempts": sum(step.get("phase") == "verify-result" for step in steps),
            "candidate": candidate,
            "route_changes": [step for step in steps if step.get("phase") == "delivery-change"],
        },
        "remaining": [] if verified_ok else fixed,
        "blockers": blockers,
        "advisories": advisories,
        "next_action": action,
        "authorization": {
            "source": "recorded-review-confirmation-and-thaw-events",
            "grants_authority": False,
            "approved": approved,
            "intent_identity": task.get("intent_identity") or "",
            "review_report_id": review.get("report_id") or "",
            "thaw_succeeded": ready,
        },
        "readiness": readiness,
        "history_refs": [
            {"kind": row["kind"], "identity": row["id"], "sha256": row["sha256"], "ref": f"{row['_source']}#{row['id']}"}
            for row in records
        ] + [
            {"kind": row["seat"], "report_id": row["report_id"], "candidate": row.get("candidate") or "", "ref": row["ref"]}
            for row in reviews
        ],
        "diagnostics": diagnostics,
    }


def record_route(root: Path, reason: str, *, requires_decision: bool = False) -> dict[str, Any]:
    from .loop import load_task
    from .store import append_task_step

    task = load_task(project_key(real_root(root)))
    if not task:
        raise ChainBroken("task-not-found: no active task")
    if not str(reason).strip():
        raise ChainBroken("route-change-reason-required")
    append_task_step(root, task["id"], "delivery-change", reason=str(reason).strip(), requires_decision=bool(requires_decision))
    return build_delivery_snapshot(root, task["id"])
