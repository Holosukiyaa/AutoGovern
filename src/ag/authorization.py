"""Authoritative intent and reviewer identity checks shared by lifecycle gates."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .critic import load_config
from .delivery import PASS, intent_identity
from .history import digest
from .managed import ChainBroken, project_key
from .store import list_llm_events
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


def _validate_sealed_review(root: Path, task: dict[str, Any], document: str, sealed: str, config: dict[str, Any] | None) -> str:
    """Match preserved facts. Only live authorization also checks current configuration."""
    review = task.get("ticket_review") or {}
    if review.get("configured") and review.get("outcome") not in PASS:
        raise ChainBroken(f"ticket-review-rejected: {review.get('report_id') or review.get('reason')}; revise ticket and run ag_start")
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
    if config is not None and config.get("enabled") and not review.get("configured"):
        raise ChainBroken("ticket-review-rejected: current reviewer has no matching opening review")
    fingerprint = review.get("review_config_identity")
    if config is not None and fingerprint and fingerprint != config_identity(config):
        raise ChainBroken("intent-identity-changed: reviewer configuration changed; review and user confirmation required")
    if review.get("configured") or review.get("report_id"):
        events = list_llm_events(root, "ticket_event", limit=0, task_id=task["id"], report_id=str(review.get("report_id") or ""))
        if len(events) != 1 or events[0].get("outcome") != review.get("outcome") or (review.get("configured") and events[0].get("outcome") not in PASS):
            raise ChainBroken("ticket-review-rejected: matching original opening report missing or rejected")
        event = events[0]
        intent, _redlines = split_document(document)
        source = review_identity(intent, str(task.get("portrait") or ""), list(task.get("anchors") or []), list(task.get("redlines") or []), task.get("goal_link"))
        if event.get("review_identity") and event["review_identity"] != source:
            raise ChainBroken("intent-identity-changed: opening review input changed")
        if event.get("review_config_identity") and review.get("review_config_identity") and event["review_config_identity"] != review["review_config_identity"]:
            raise ChainBroken("intent-identity-changed: original review configuration facts conflict")
        fingerprint = event.get("review_config_identity") or review.get("review_config_identity")
        if config is not None and fingerprint and fingerprint != config_identity(config):
            raise ChainBroken("intent-identity-changed: reviewer configuration changed; review and user confirmation required")
        if config is not None and review.get("configured") and config.get("enabled") is not True:
            raise ChainBroken("config-error: reviewed ticket requires its independent reviewer to remain enabled")
    return identity


def _validate_preserved_ticket(root: Path, task: dict[str, Any], document: str, sealed: str) -> str:
    """Resume preparation validates the old review against its own recorded inputs.

    A changed reviewer must review the new ticket before confirmation can succeed.
    This historical check grants no construction or confirmation authority.
    """
    return _validate_sealed_review(root, task, document, sealed, None)


def _live_ticket_identity(root: Path, task: dict[str, Any]) -> str:
    try:
        config = load_config(root, read_only=True)
    except (OSError, ValueError, TypeError, ChainBroken) as exc:
        raise ChainBroken(f"config-error: {exc}") from exc
    if config.get("error"):
        raise ChainBroken(f"config-error: {config['error']}")
    document = require_ticket(root)
    try:
        sealed = copy_path(root).read_text(encoding="utf-8")
    except OSError as exc:
        raise ChainBroken(f"intent-identity-changed: sealed redlines unavailable: {exc}") from exc
    return _validate_sealed_review(root, task, document, sealed, config)


def validate_ticket(root: Path, task: dict[str, Any]) -> str:
    from .decisions import pending_decisions

    identity = _live_ticket_identity(root, task)
    if pending_decisions(root, task["id"]):
        raise ChainBroken("await-user-decision: use ag resume with the explicit pending change IDs, then user confirm-map")
    return identity


def validate_confirmation(root: Path, task: dict[str, Any]) -> str:
    """Only the human confirmation gate may handle a reviewed, unresolved resume."""
    from .decisions import confirmation_preparation, pending_decisions

    identity = _live_ticket_identity(root, task)
    if pending_decisions(root, task["id"]) and not confirmation_preparation(root, task):
        raise ChainBroken("await-user-decision: pending decisions have no matching reviewed resume preparation")
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
