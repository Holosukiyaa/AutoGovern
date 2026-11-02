"""Authoritative intent and reviewer identity checks shared by lifecycle gates."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .critic import load_config
from .delivery import PASS, intent_identity
from .history import digest
from .managed import ChainBroken, project_key
from .store import list_llm_events, load_task_timeline
from .ticket_doc import copy_path, require_ticket, split_document


def config_identity(config: dict[str, Any]) -> str:
    return digest({name: config.get(name) for name in ("enabled", "endpoint", "model", "worker_model", "allow_same_family")})


def review_identity(intent_body: str, portrait: str, anchors: list[Any], redlines: list[Any], goal_link: dict[str, Any] | None = None) -> str:
    return digest({"intent_body": intent_body.rstrip(), "portrait": portrait, "anchors": anchors, "redlines": redlines, "goal_link": goal_link})


def bind_ticket(root: Path, task: dict[str, Any]) -> None:
    document = require_ticket(root)
    sealed = copy_path(root).read_text(encoding="utf-8")
    task["intent_identity"] = intent_identity(task, document, sealed)
    review = task.get("ticket_review") or {}
    review["task_id"] = task["id"]
    task["ticket_review"] = review
    task["worktree_ready"] = False
    task.pop("authorization_identity", None)
    task.pop("thaw_error", None)
    task["intent_map_confirmed"] = False


def validate_ticket(root: Path, task: dict[str, Any]) -> str:
    try:
        config = load_config(root, read_only=True)
    except (OSError, ValueError, TypeError, ChainBroken) as exc:
        raise ChainBroken(f"config-error: {exc}") from exc
    if config.get("error"):
        raise ChainBroken(f"config-error: {config['error']}")
    review = task.get("ticket_review") or {}
    if review.get("configured") and review.get("outcome") not in PASS:
        raise ChainBroken(f"ticket-review-rejected: {review.get('report_id') or review.get('reason')}; revise ticket and run ag_start")
    document = require_ticket(root)
    try:
        sealed = copy_path(root).read_text(encoding="utf-8")
    except OSError as exc:
        raise ChainBroken(f"intent-identity-changed: sealed redlines unavailable: {exc}") from exc
    identity = intent_identity(task, document, sealed)
    expected = task.get("intent_identity")
    if not expected:
        original = str(task.get("anchor_preview") or "")
        original_seal = "\n".join(task.get("redlines") or []) + ("\n" if task.get("redlines") else "")
        expected = intent_identity(task, original, original_seal)
    if identity != expected or (task.get("authorization_identity") and task["authorization_identity"] != identity):
        raise ChainBroken("intent-identity-changed: ticket, fixed result, or hard boundary changed; review and user confirmation required")
    if review.get("task_id", task["id"]) != task["id"]:
        raise ChainBroken("intent-identity-changed: opening report belongs to another task")
    if config.get("enabled") and not review.get("configured"):
        raise ChainBroken("ticket-review-rejected: current reviewer has no matching opening review")
    fingerprint = review.get("review_config_identity")
    if fingerprint and fingerprint != config_identity(config):
        raise ChainBroken("intent-identity-changed: reviewer configuration changed; review and user confirmation required")
    if review.get("configured"):
        events = list_llm_events(root, "ticket_event", limit=0, task_id=task["id"], report_id=str(review.get("report_id") or ""))
        if len(events) != 1 or events[0].get("outcome") not in PASS:
            raise ChainBroken("ticket-review-rejected: matching original opening report missing or rejected")
        event = events[0]
        intent, _redlines = split_document(document)
        source = review_identity(intent, str(task.get("portrait") or ""), list(task.get("anchors") or []), list(task.get("redlines") or []), task.get("goal_link"))
        if event.get("review_identity") and event["review_identity"] != source:
            raise ChainBroken("intent-identity-changed: opening review input changed")
        fingerprint = event.get("review_config_identity") or review.get("review_config_identity")
        if fingerprint and fingerprint != config_identity(config):
            raise ChainBroken("intent-identity-changed: reviewer configuration changed; review and user confirmation required")
        if config.get("enabled") is not True:
            raise ChainBroken("config-error: reviewed ticket requires its independent reviewer to remain enabled")
    for step in load_task_timeline(root, task["id"])["steps"]:
        if step.get("phase") == "delivery-change" and step.get("requires_decision"):
            raise ChainBroken("await-user-decision: confirmed commitment or hard boundary needs a user decision")
    return identity


def require_construction(root: Path, task: dict[str, Any]) -> None:
    if task.get("process") in {"completed", "abandoned"}:
        raise ChainBroken("cleanup-pending: task is closing; retry its finish/abandon operation")
    if not task.get("intent_map_confirmed"):
        raise ChainBroken("intent-map-unconfirmed: user must personally confirm the map")
    identity = validate_ticket(root, task)
    if task.get("thaw_error") or ("worktree_ready" in task and not task["worktree_ready"]):
        raise ChainBroken("thaw-failed: approval is recorded but construction is not ready; user must retry confirmation")
    from .freeze import _tracked_files, assert_frozen

    try:
        assert_frozen(_tracked_files(root))
    except OSError as exc:
        raise ChainBroken(f"canonical-freeze-missing: {exc}") from exc
    tree = Path(str(task.get("worktree") or ""))
    try:
        for path in _tracked_files(tree):
            descriptor = os.open(path, os.O_WRONLY)
            os.close(descriptor)
    except OSError as exc:
        raise ChainBroken(f"thaw-failed: live construction permissions are unavailable: {exc}") from exc
    if "worktree_ready" not in task:
        from .loop import save_task
        from .store import append_task_step

        task["worktree_ready"] = True
        task["intent_identity"] = identity
        task["authorization_identity"] = identity
        append_task_step(root, task["id"], "worktree-observed-ready", source="legacy-confirmation-and-live-permissions", intent_identity=identity)
        save_task(project_key(root), task)
