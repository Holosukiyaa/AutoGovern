"""Append-only decision preparation; only confirm-map can complete a resume."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from .history import digest
from .managed import ChainBroken, ag_home, lookup_project, project_key, real_root
from .store import append_task_step, list_llm_events, load_task_timeline


def _valid_ids(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and bool(item.strip()) for item in value) and len(value) == len(set(value))


def _review_proof(root: Path, task_id: str, step: dict[str, Any], *, passed: bool = False) -> None:
    """Reject orphaned/corrupt review facts rather than trusting an empty report ID."""
    from .authorization import review_identity
    from .delivery import intent_identity
    from .ticket_doc import split_document

    snapshot = step.get("reviewed_task")
    if not isinstance(snapshot, dict) or snapshot.get("id") != task_id or not isinstance(step.get("configured"), bool):
        raise ChainBroken("history-source-error: decision review identity is incomplete")
    document = str(snapshot.get("anchor_preview") or "")
    seal = "\n".join(snapshot.get("redlines") or []) + ("\n" if snapshot.get("redlines") else "")
    intent, _ = split_document(document)
    source = review_identity(intent, str(snapshot.get("portrait") or ""), list(snapshot.get("anchors") or []), list(snapshot.get("redlines") or []), snapshot.get("goal_link"))
    if intent_identity(snapshot, document, seal) != step.get("intent_identity") or source != step.get("review_identity") or not step.get("review_config_identity"):
        raise ChainBroken("history-source-error: decision review input or sealed identity changed")
    report_id = step.get("report_id")
    if report_id:
        events = list_llm_events(root, "ticket_event", limit=0, task_id=task_id, report_id=report_id)
        if len(events) != 1 or events[0].get("review_identity") != source or events[0].get("review_config_identity") != step["review_config_identity"] or events[0].get("outcome") != step.get("outcome") or (passed and (not step["configured"] or events[0].get("outcome") not in {"passed", "pass", "allow"})):
            raise ChainBroken("history-source-error: decision has no matching independent review")
    elif passed or step["configured"] or step.get("reason") != "not-configured":
        raise ChainBroken("history-source-error: unconfigured decision review has no matching source")


def _steps(root: Path, task_id: str) -> list[dict[str, Any]]:
    timeline = load_task_timeline(root, task_id)
    if timeline.get("diagnostics"):
        raise ChainBroken("history-source-error: decision history has conflicting task identities")
    return timeline["steps"]


def _change_id(task_id: str, step: dict[str, Any]) -> str:
    explicit = step.get("change_id")
    if explicit is not None:
        if not isinstance(explicit, str) or not explicit.strip():
            raise ChainBroken("history-source-error: invalid decision change ID")
        return explicit
    return "legacy_" + digest({"task_id": task_id, "step": step})


def pending_decisions(root: Path, task_id: str) -> list[dict[str, Any]]:
    """One truth for authorization and views, including legacy route records."""
    pending: dict[str, dict[str, Any]] = {}
    prepared: dict[str, dict[str, Any]] = {}
    reviewed: dict[str, dict[str, Any]] = {}
    confirmed: set[tuple[str, str]] = set()
    ready: set[tuple[str, str]] = set()
    resolved: set[str] = set()
    for step in _steps(root, task_id):
        phase = step.get("phase")
        if phase == "delivery-change" and step.get("requires_decision"):
            identity = _change_id(task_id, step)
            if identity in pending or identity in resolved:
                raise ChainBroken("history-identity-conflict: ambiguous decision change ID")
            pending[identity] = {**step, "change_id": identity}
        elif phase == "decision-prepared":
            preparation = step.get("preparation")
            if not isinstance(preparation, dict) or preparation.get("task_id") != task_id:
                raise ChainBroken("history-source-error: invalid decision preparation")
            rid = str(preparation.get("resume_id") or "")
            ids = preparation.get("change_ids")
            if not rid or rid in prepared or not _valid_ids(ids) or set(ids) != set(pending) or not preparation.get("decision"):
                raise ChainBroken("history-source-error: ambiguous decision preparation")
            origin = preparation.get("previous_task")
            if not isinstance(origin, dict) or origin.get("id") != task_id or not origin.get("intent_map_confirmed") or not preparation.get("previous_identity") or not preparation.get("candidate") or not preparation.get("worktree_head"):
                raise ChainBroken("history-source-error: decision preparation lost its confirmed predecessor")
            prepared[rid] = preparation
        elif phase == "decision-reviewed":
            rid = str(step.get("resume_id") or "")
            if rid not in prepared or rid in reviewed or not step.get("intent_identity"):
                raise ChainBroken("history-source-error: decision review has no unique preparation")
            _review_proof(root, task_id, step)
            origin = prepared[rid]["previous_task"]
            snapshot = step["reviewed_task"]
            if any(snapshot.get(name) != origin.get(name) for name in ("id", "source_head", "worktree")) or (step.get("configured") and step.get("report_id") == (origin.get("ticket_review") or {}).get("report_id")):
                raise ChainBroken("history-source-error: resume changed task identity or reused its old review")
            reviewed[rid] = step
        elif phase == "intent-map-confirmed" and step.get("resume_id"):
            rid = str(step["resume_id"])
            review = reviewed.get(rid) or {}
            if not review or step.get("intent_identity") != review.get("intent_identity"):
                raise ChainBroken("history-source-error: decision approval has no matching review")
            confirmed.add((rid, str(step["intent_identity"])))
        elif phase == "worktree-ready" and step.get("resume_id"):
            proof = (str(step["resume_id"]), str(step.get("intent_identity") or ""))
            if proof not in confirmed:
                raise ChainBroken("history-source-error: decision thaw has no matching approval")
            ready.add(proof)
        elif phase == "decision-resolved":
            rid = str(step.get("resume_id") or "")
            preparation = prepared.get(rid) or {}
            review = reviewed.get(rid) or {}
            ids = step.get("change_ids")
            proof = (rid, str(step.get("intent_identity") or ""))
            if not preparation or not review or proof not in ready or step.get("intent_identity") != review.get("intent_identity") or step.get("report_id") != review.get("report_id") or ids != preparation.get("change_ids") or set(ids) != set(pending):
                raise ChainBroken("history-source-error: decision resolution lacks exact review, approval and thaw evidence")
            _review_proof(root, task_id, review, passed=True)
            for identity in ids:
                pending.pop(identity)
                resolved.add(identity)
    return list(pending.values())


def _preparation(root: Path, task: dict[str, Any]) -> dict[str, Any] | None:
    cached = task.get("resume_preparation")
    if cached is None:
        return None
    if not isinstance(cached, dict) or cached.get("task_id") != task["id"]:
        raise ChainBroken("history-source-error: invalid active resume preparation")
    matches = [step["preparation"] for step in _steps(root, task["id"]) if step.get("phase") == "decision-prepared" and isinstance(step.get("preparation"), dict) and step["preparation"].get("resume_id") == cached.get("resume_id")]
    if len(matches) != 1 or matches[0] != cached:
        raise ChainBroken("history-source-error: resume preparation does not match its original fact")
    return cached


def reviewed_preparation(root: Path, task: dict[str, Any]) -> dict[str, Any] | None:
    preparation = _preparation(root, task)
    pending = pending_decisions(root, task["id"])
    if not preparation or not pending or set(preparation["change_ids"]) != {row["change_id"] for row in pending}:
        return None
    reviews = [step for step in _steps(root, task["id"]) if step.get("phase") == "decision-reviewed" and step.get("resume_id") == preparation["resume_id"]]
    current = task.get("ticket_review") or {}
    if len(reviews) != 1 or reviews[0].get("intent_identity") != task.get("intent_identity") or reviews[0].get("report_id") != str(current.get("report_id") or "") or not current.get("configured") or current.get("outcome") not in {"passed", "pass", "allow"}:
        return None
    return preparation


def confirmation_preparation(root: Path, task: dict[str, Any]) -> dict[str, Any] | None:
    preparation = reviewed_preparation(root, task)
    if preparation:
        from .loop import git, tree_digest

        worktree = Path(task["worktree"])
        if git(worktree, "rev-parse", "HEAD") != preparation["worktree_head"] or tree_digest(worktree) != preparation["candidate"]:
            raise ChainBroken("intent-identity-changed: resume worktree candidate changed after preparation")
    return preparation


def record_resume_review(root: Path, task: dict[str, Any]) -> None:
    from .authorization import config_identity, review_identity
    from .critic import load_config
    from .ticket_doc import split_document

    preparation = _preparation(root, task)
    if not preparation:
        return
    review = task.get("ticket_review") or {}
    names = ("id", "source_head", "worktree", "portrait", "anchors", "fixed", "goal_link", "redlines", "anchor_preview")
    snapshot = {name: task[name] for name in names if name in task}
    intent, _ = split_document(str(task.get("anchor_preview") or ""))
    source = review_identity(intent, str(task.get("portrait") or ""), list(task.get("anchors") or []), list(task.get("redlines") or []), task.get("goal_link"))
    append_task_step(root, task["id"], "decision-reviewed", resume_id=preparation["resume_id"], intent_identity=task["intent_identity"], report_id=str(review.get("report_id") or ""), configured=bool(review.get("configured")), outcome=review.get("outcome"), reason=review.get("reason"), review_identity=source, review_config_identity=config_identity(load_config(root, read_only=True)), reviewed_task=snapshot)


def resolve_after_thaw(root: Path, task: dict[str, Any], preparation: dict[str, Any] | None) -> None:
    if preparation:
        append_task_step(root, task["id"], "decision-resolved", resume_id=preparation["resume_id"], change_ids=preparation["change_ids"], intent_identity=task["intent_identity"], report_id=str((task.get("ticket_review") or {}).get("report_id") or ""))


def _verify_site(root: Path, task: dict[str, Any]) -> Path:
    from .freeze import _tracked_files, assert_frozen
    from .loop import _dirty, _hook_ok, _is_canonical, _posix, git

    key = project_key(root)
    if not _is_canonical(root) or not _hook_ok(root, key):
        raise ChainBroken("hook-removed: resume requires the enrolled canonical checkout and gate")
    if _dirty(root):
        raise ChainBroken("canonical-dirty: clean canonical before preparing a decision")
    if git(root, "rev-parse", "HEAD") != task.get("source_head") or git(root, "symbolic-ref", "--short", "HEAD") != task.get("branch"):
        raise ChainBroken("intent-identity-changed: canonical candidate or branch changed")
    worktree = Path(str(task.get("worktree") or ""))
    expected = (ag_home() / "worktrees" / key / task["id"]).resolve()
    if worktree.resolve() != expected or not worktree.is_dir():
        raise ChainBroken("intent-identity-changed: resume worktree changed or is missing")
    blocks = git(root, "worktree", "list", "--porcelain").strip().split("\n\n")
    if not any(block.splitlines()[0] == "worktree " + _posix(worktree.resolve()) and f"branch refs/heads/ag/{task['id']}" in block.splitlines() for block in blocks):
        raise ChainBroken("intent-identity-changed: resume worktree registration changed")
    try:
        assert_frozen(_tracked_files(root))
    except OSError as exc:
        raise ChainBroken(f"canonical-freeze-missing: {exc}") from exc
    return worktree


def prepare_resume(root: Path, *, change_ids: list[str], decision: str) -> dict[str, Any]:
    """Freeze and independently review a decision on the same ticket, never approve it."""
    from .authorization import _validate_preserved_ticket
    from .delivery import task_facts
    from .freeze import _tracked_files, assert_frozen, freeze_worktree
    from .loop import git, load_task, save_task, start, tree_digest
    from .ticket_doc import copy_path, require_ticket, split_document

    root = real_root(root)
    if not lookup_project(root):
        raise ChainBroken(f"not-enrolled: {root}")
    task = load_task(project_key(root))
    if not task or task.get("process") in {"completed", "abandoned"}:
        raise ChainBroken("task-not-found: resume requires an active task")
    if not isinstance(change_ids, list) or not change_ids or any(not isinstance(item, str) or not item.strip() for item in change_ids) or len(set(change_ids)) != len(change_ids):
        raise ChainBroken("decision-identity-required: provide unique explicit change IDs")
    if not isinstance(decision, str) or not decision.strip():
        raise ChainBroken("decision-required: provide the user's explicit decision")
    pending = pending_decisions(root, task["id"])
    if set(change_ids) != {row["change_id"] for row in pending}:
        raise ChainBroken("decision-identity-mismatch: IDs must identify all current unresolved changes of this task; unknown or consumed IDs are refused")
    worktree = _verify_site(root, task)
    previous = _preparation(root, task)
    unresolved_previous = previous and any(row["change_id"] in previous["change_ids"] for row in pending)
    if unresolved_previous:
        if task.get("intent_map_confirmed"):
            raise ChainBroken("resume-confirmation-recorded: approval retained; retry user confirm-map to complete thaw")
        origin = previous["previous_task"]
        original_seal = previous["previous_seal"]
        if git(worktree, "rev-parse", "HEAD") != previous["worktree_head"] or tree_digest(worktree) != previous["candidate"]:
            raise ChainBroken("intent-identity-changed: prepared candidate changed")
    else:
        if not task.get("intent_map_confirmed"):
            raise ChainBroken("intent-map-unconfirmed: resume requires a previously confirmed task")
        origin = {name: value for name, value in task_facts(task).items() if name != "resume_preparation"}
        original_seal = copy_path(root).read_text(encoding="utf-8")
    original_identity = _validate_preserved_ticket(root, origin, str(origin.get("anchor_preview") or ""), original_seal)
    intent, _redlines = split_document(require_ticket(root))
    freeze_worktree(worktree)
    try:
        assert_frozen(_tracked_files(worktree))
    except OSError as exc:
        raise ChainBroken(f"resume-freeze-failed: task retained: {exc}") from exc
    preparation = {"resume_id": "resume_" + uuid.uuid4().hex, "task_id": task["id"], "change_ids": sorted(change_ids), "decision": decision.strip(), "previous_identity": original_identity, "previous_task": origin, "previous_seal": original_seal, "worktree_head": git(worktree, "rev-parse", "HEAD"), "candidate": tree_digest(worktree)}
    append_task_step(root, task["id"], "decision-prepared", preparation=preparation)
    task["resume_preparation"] = preparation
    task["intent_map_confirmed"] = False
    task["worktree_ready"] = False
    task.pop("authorization_identity", None)
    task.pop("thaw_error", None)
    save_task(project_key(root), task)
    # Reuse the ordinary sealing/review path. A crash remains frozen and retryable.
    from .anchor_map import resolve_fixed

    result = start(root, portrait=intent.strip(), fixed=resolve_fixed(intent))
    return {**result, "schema": "ag.resume.v1", "resume_preparation": preparation}
