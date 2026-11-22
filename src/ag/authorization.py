"""Authoritative intent and reviewer identity checks shared by lifecycle gates."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .critic import load_config
from .delivery import PASS
from .history import digest
from .managed import ChainBroken, project_key
from .store import list_llm_events
from .ticket_package import load_seal, package_identity, sealed_dir


def recorded(task: dict[str, Any]) -> bool:
    """Presence only. Construction must additionally validate live authorization."""
    return bool(task.get("intent_map_confirmed"))


def require_single_ticket(task: dict[str, Any]) -> None:
    if "long_goal" in task:
        raise ChainBroken("long-ticket-retired: use abandon to close this ticket; archived long data is left untouched")


def config_identity(config: dict[str, Any]) -> str:
    return digest({name: config.get(name) for name in ("enabled", "endpoint", "model", "worker_model", "allow_same_family")})


def review_identity(intent_body: str, portrait: str, anchors: list[Any], redlines: list[Any], goal_link: dict[str, Any] | None = None) -> str:
    return digest({"intent_body": intent_body.rstrip(), "portrait": portrait, "anchors": anchors, "redlines": redlines, "goal_link": goal_link})


def bind_ticket(root: Path, task: dict[str, Any]) -> None:
    folder = sealed_dir(root, task["id"])
    seal = load_seal(root, task)
    task["intent_identity"] = package_identity(seal)
    task["original_ticket"] = {"task_id": task["id"], "path": str(folder / "ticket.md"), "sha256": seal["files"]["ticket.md"]}
    review = task.get("ticket_review") or {}
    review["task_id"] = task["id"]
    task["ticket_review"] = review
    task["worktree_ready"] = False
    task.pop("authorization_identity", None)
    task.pop("thaw_error", None)
    task["intent_map_confirmed"] = False


def _validate_sealed_review(root: Path, task: dict[str, Any], document: str, sealed: dict[str, Any], config: dict[str, Any] | None) -> str:
    """Match preserved facts. Only live authorization also checks current configuration."""
    review = task.get("ticket_review") or {}
    if review.get("configured") and review.get("outcome") not in PASS:
        raise ChainBroken(f"ticket-review-rejected: {review.get('report_id') or review.get('reason')}; revise ticket and run ag_start")
    identity = package_identity(sealed)
    if identity != task.get("intent_identity") or (task.get("authorization_identity") and task["authorization_identity"] != identity):
        raise ChainBroken("seal-invalid: sealed package identity changed")
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
        source = review_identity(document, str(task.get("portrait") or ""), list(task.get("anchors") or []), list(task.get("redlines") or []), task.get("goal_link"))
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


def _live_ticket_identity(root: Path, task: dict[str, Any]) -> str:
    try:
        config = load_config(root, read_only=True)
    except (OSError, ValueError, TypeError, ChainBroken) as exc:
        raise ChainBroken(f"config-error: {exc}") from exc
    if config.get("error"):
        raise ChainBroken(f"config-error: {config['error']}")
    sealed = load_seal(root, task)
    document = (sealed_dir(root, task["id"]) / "ticket.md").read_text(encoding="utf-8")
    return _validate_sealed_review(root, task, document, sealed, config)


def validate_ticket(root: Path, task: dict[str, Any]) -> str:
    require_single_ticket(task)
    if recorded(task):
        from .presence import require_authorization
        require_authorization(root, task)
    return _live_ticket_identity(root, task)


def validate_confirmation(root: Path, task: dict[str, Any]) -> str:
    return validate_ticket(root, task)


def require_construction(root: Path, task: dict[str, Any]) -> None:
    require_single_ticket(task)
    from .site import require_running
    require_running(task)
    if task.get("process") in {"completed", "abandoned"}:
        raise ChainBroken("cleanup-pending: task is closing; retry its finish/abandon operation")
    if not recorded(task):
        raise ChainBroken("intent-map-unconfirmed: approval requires human confirm-map")
    identity = validate_ticket(root, task)
    if task.get("thaw_error") or ("worktree_ready" in task and not task["worktree_ready"]):
        raise ChainBroken("thaw-failed: approval is recorded but construction is not ready; retry human confirm-map")
    assert_live_construction(root, task)
    if "worktree_ready" not in task:
        from .workspace import save_task
        from .store import append_task_step

        task["worktree_ready"] = True
        task["intent_identity"] = identity
        task["authorization_identity"] = identity
        append_task_step(root, task["id"], "worktree-observed-ready", source="legacy-confirmation-and-live-permissions", intent_identity=identity)
        save_task(project_key(root), task)


def assert_live_construction(root: Path, task: dict[str, Any]) -> None:
    """Read-only permission observation shared by views and action gates."""
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
