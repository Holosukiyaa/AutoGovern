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

    validate_long_binding(root, task)
    identity = _live_ticket_identity(root, task)
    if pending_decisions(root, task["id"]):
        raise ChainBroken("await-user-decision: use ag resume with the explicit pending change IDs, then user confirm-map")
    return identity


def validate_confirmation(root: Path, task: dict[str, Any]) -> str:
    """Only the human confirmation gate may handle a reviewed, unresolved resume."""
    from .decisions import confirmation_preparation, pending_decisions

    validate_long_binding(root, task, confirmation=True)
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



def _long_pending(goal: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in goal.get("decisions", []) if row.get("status", row.get("state", "pending")) in {"pending", "proposed", "awaiting-decision"}]


def new_long_binding(root: Path, goal_id: str, *, result_ids: list[str] | None = None, contribution: str = "", pending: bool = False) -> dict[str, Any]:
    from .long_tasks import read_goal, ticket_projection, work_package
    import hashlib

    goal = read_goal(root, goal_id)
    pending = bool(pending and _long_pending(goal))
    contribution = contribution or goal["title"]
    chosen = list(result_ids or [row["id"] for row in goal["results"] if row.get("state") == "active"])
    package = work_package(root, goal_id, chosen, contribution=contribution)
    text = ticket_projection(root, goal_id, pending=pending, result_ids=chosen, contribution=contribution)
    proposals = _long_pending(goal) if pending else []
    stable = {"goal_id": goal_id, "intent_revision": goal["intent_revision"], "result_ids": chosen, "contribution": contribution, "proposal_ids": [row["id"] for row in proposals], "proposal_hashes": [row["preview_hash"] for row in proposals], "projection_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    return {**stable, "opened_revision": goal["revision"], "work_package": package, "return_to": package.get("return_to"), "projection": text, "preview_token": digest(stable)}


def long_goal_link(binding: dict[str, Any]) -> dict[str, Any]:
    return {key: binding[key] for key in ("goal_id", "intent_revision", "result_ids", "contribution", "proposal_ids", "proposal_hashes", "projection_sha256")}


def prepare_long_projection(root: Path, task: dict[str, Any], *, pending: bool = False) -> None:
    """Only start/resume may replace the one-way exam snapshot; never reads."""
    binding = task["long_goal"]
    if task.get("intent_map_confirmed") and not pending:
        return
    fresh = new_long_binding(root, binding["goal_id"], result_ids=binding["result_ids"], contribution=binding["contribution"], pending=pending)
    task["long_goal"] = fresh
    task["goal_link"] = long_goal_link(fresh)
    from .ticket_doc import ticket_path

    ticket_path(root).write_text(fresh["projection"], encoding="utf-8")


def _accepted_long_binding(goal: dict[str, Any], task: dict[str, Any]) -> bool:
    binding = task["long_goal"]
    ids = binding.get("proposal_ids") or []
    proof = goal.get("authorization") or {}
    if proof.get("task_id") != task["id"] or proof.get("intent_identity") != task.get("intent_identity") or proof.get("preview_token") != binding.get("preview_token"):
        return False
    return goal["intent_revision"] == binding["intent_revision"] + len(ids) and all(any(row["id"] == identity and row.get("state") == "accepted" and (row.get("authorization") or {}).get("preview_token") == binding["preview_token"] for row in goal["decisions"]) for identity in ids)


def validate_long_binding(root: Path, task: dict[str, Any], *, confirmation: bool = False) -> None:
    binding = task.get("long_goal")
    if not binding:
        return
    from .long_tasks import read_goal, ticket_projection
    import hashlib

    goal = read_goal(root, binding["goal_id"])
    accepted = _accepted_long_binding(goal, task)
    pending = _long_pending(goal)
    reviewed = set(binding.get("proposal_ids") or [])
    if pending and (not confirmation or {row["id"] for row in pending} != reviewed):
        raise ChainBroken("await-user-decision: long goal has pending intent changes; route --requires-decision then resume")
    if not accepted and goal["intent_revision"] != binding["intent_revision"]:
        raise ChainBroken("long-intent-revision-changed: review and human confirmation required")
    projection = ticket_projection(root, binding["goal_id"], pending=bool(reviewed and not accepted), result_ids=binding["result_ids"], contribution=binding["contribution"])
    if hashlib.sha256(projection.encode("utf-8")).hexdigest() != binding["projection_sha256"]:
        raise ChainBroken("long-intent-projection-changed: re-review and human confirmation required")


def validate_long_preview(root: Path, task: dict[str, Any], token: str) -> None:
    from .long_tasks import read_goal

    binding = task["long_goal"]
    accepted = _accepted_long_binding(read_goal(root, binding["goal_id"]), task)
    current_token = binding["preview_token"] if accepted else new_long_binding(root, binding["goal_id"], result_ids=binding["result_ids"], contribution=binding["contribution"], pending=bool(binding.get("proposal_ids")))["preview_token"]
    if not token or token != binding.get("preview_token") or token != current_token:
        raise ChainBroken("stale-long-preview: display start/resume again and personally confirm its exact --preview token")


def record_long_authorization(root: Path, task: dict[str, Any]) -> None:
    from . import long_tasks

    binding = task["long_goal"]
    long_tasks.record_authorization(root, binding["goal_id"], task_id=task["id"], intent_revision=binding["intent_revision"], proposal_ids=binding.get("proposal_ids") or [], preview_token=binding["preview_token"], authorization={"intent_identity": task["intent_identity"]})


def record_long_close(root: Path, task: dict[str, Any], *, process: str, product: str) -> None:
    from . import long_tasks

    binding = task["long_goal"]
    long_tasks.record_iteration(root, binding["goal_id"], task_id=task["id"], contribution=binding["contribution"], process=process, product=product, return_to=binding.get("return_to"), evidence=task.get("verify") or {})
