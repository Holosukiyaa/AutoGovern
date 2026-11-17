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
    from .ticket_doc import preserve_original_ticket
    task["original_ticket"] = preserve_original_ticket(root, task["id"], document)
    review = task.get("ticket_review") or {}
    review["task_id"] = task["id"]
    task["ticket_review"] = review
    task["worktree_ready"] = False
    task.pop("authorization_identity", None)
    task.pop("long_authorization", None)
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
    if task.get("long_authorization"):
        from .long_authorization import validate_inherited
        validate_inherited(root, task)
    elif task.get("long_goal") and task.get("intent_map_confirmed"):
        from .long_authorization import validate_direct
        validate_direct(root, task)
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
    from .long_authorization import recorded
    if not recorded(task):
        raise ChainBroken("intent-map-unconfirmed: first approval requires human confirm-map; approved long children resume with start")
    identity = validate_ticket(root, task)
    if task.get("thaw_error") or ("worktree_ready" in task and not task["worktree_ready"]):
        raise ChainBroken("thaw-failed: approval is recorded but construction is not ready; retry start for long, human confirm-map for single")
    if task.get("long_goal"):
        from .long_authorization import activation_complete
        if not activation_complete(root, task):
            raise ChainBroken("thaw-failed: long activation registration is incomplete; retry start with the retained approval")
    assert_live_construction(root, task)
    if "worktree_ready" not in task:
        from .loop import save_task
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


def _long_pending(goal: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in goal.get("decisions", []) if row.get("status", row.get("state", "pending")) in {"pending", "proposed", "awaiting-decision"}]


def new_long_binding(root: Path, goal_id: str, *, result_ids: list[str] | None = None, contribution: str = "", pending: bool = False) -> dict[str, Any]:
    from .long_tasks import read_goal, ticket_projection, work_package
    import hashlib

    goal = read_goal(root, goal_id)
    if goal.get("read_only") or goal.get("format") == "legacy-sqlite":
        raise ChainBroken("long-legacy-read-only: use explicit long migrate to create an unauthorized Markdown draft before start")
    pending = bool(pending and _long_pending(goal))
    contribution = contribution or goal["title"]
    chosen = list(result_ids or [row["id"] for row in goal["results"] if row.get("state") == "active"])
    package = work_package(root, goal_id, chosen, contribution=contribution)
    text = ticket_projection(root, goal_id, pending=pending, result_ids=chosen, contribution=contribution)
    proposals = _long_pending(goal) if pending else []
    stable = {"goal_id": goal_id, "intent_revision": goal["intent_revision"], "result_ids": chosen, "contribution": contribution, "proposal_ids": [row["id"] for row in proposals], "proposal_hashes": [row["preview_hash"] for row in proposals], "projection_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    if goal.get("format") == "markdown":
        from .long_tasks import preview_intent
        effective = preview_intent(root, goal_id, pending=pending)
        stable.update(ticket_type="long", authority="markdown", document_path=goal["document_path"], intent_sha256=goal["intent_sha256"], preview_intent_sha256=effective["intent_sha256"], preview_intent_revision=effective["intent_revision"])
    return {**stable, "document_sha256": goal.get("document_sha256"), "opened_revision": goal["revision"], "work_package": package, "return_to": package.get("return_to"), "projection": text, "preview_token": digest({**stable, "document_sha256": goal.get("document_sha256")})}


def long_goal_link(binding: dict[str, Any]) -> dict[str, Any]:
    return {key: binding[key] for key in ("goal_id", "intent_revision", "result_ids", "contribution", "proposal_ids", "proposal_hashes", "projection_sha256", "ticket_type", "authority", "document_path", "intent_sha256", "preview_intent_sha256", "preview_intent_revision") if key in binding}


def prepare_long_projection(root: Path, task: dict[str, Any], *, pending: bool = False) -> None:
    """Only start/resume may replace the one-way exam snapshot; never reads."""
    binding = task["long_goal"]
    from .long_authorization import recorded
    if recorded(task) and not pending:
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
    expected = binding.get("preview_intent_revision", binding["intent_revision"] + len(ids))
    if goal.get("format") == "markdown" and goal.get("intent_sha256") != binding.get("preview_intent_sha256", binding.get("intent_sha256")):
        return False
    return goal["intent_revision"] == expected and goal.get("authorized_intent_revision") == expected and all(any(row["id"] == identity and row.get("state") == "accepted" and (row.get("authorization") or {}).get("preview_token") == binding["preview_token"] for row in goal["decisions"]) for identity in ids)


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
    if not accepted and (goal["intent_revision"] != binding["intent_revision"] or binding.get("intent_sha256") and goal.get("intent_sha256") != binding["intent_sha256"]):
        raise ChainBroken("long-intent-revision-changed: review and human confirmation required")
    projection = ticket_projection(root, binding["goal_id"], pending=bool(reviewed and not accepted), result_ids=binding["result_ids"], contribution=binding["contribution"])
    if hashlib.sha256(projection.encode("utf-8")).hexdigest() != binding["projection_sha256"]:
        legacy = ticket_projection(root, binding["goal_id"], pending=bool(reviewed and not accepted), result_ids=binding["result_ids"], contribution=binding["contribution"], authorization_context=False)
        if hashlib.sha256(legacy.encode("utf-8")).hexdigest() != binding["projection_sha256"]:
            raise ChainBroken("long-intent-projection-changed: re-review the child scope; changed parent intent requires human confirmation")


def validate_long_preview(root: Path, task: dict[str, Any], token: str) -> None:
    from .long_tasks import read_goal

    binding = task["long_goal"]
    accepted = _accepted_long_binding(read_goal(root, binding["goal_id"]), task)
    current_token = binding["preview_token"] if accepted else new_long_binding(root, binding["goal_id"], result_ids=binding["result_ids"], contribution=binding["contribution"], pending=bool(binding.get("proposal_ids")))["preview_token"]
    if not token or token != binding.get("preview_token") or token != current_token:
        raise ChainBroken("stale-long-preview: display start/resume again and personally confirm its exact --preview token")


def _require_preserved_abandon(root: Path, task: dict[str, Any]) -> None:
    """A deferred parent view is valid only after real close material is durable."""
    import hashlib
    from .history import read_records
    from .loop import git

    original = task.get("original_ticket") or {}
    archive = task.get("candidate_archive") or {}
    path = Path(str(original.get("path") or ""))
    if task.get("process") != "abandoned" or original.get("task_id") != task.get("id") or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != original.get("sha256"):
        raise ChainBroken("long-view-deferred-proof-missing: abandoned original ticket is not preserved")
    reference = "refs/ag/abandoned/" + task["id"]
    if archive.get("ref") != reference or not archive.get("candidate") or git(root, "rev-parse", reference + "^{tree}", check=False) != archive["candidate"] or git(root, "rev-parse", reference, check=False) != archive.get("commit"):
        raise ChainBroken("long-view-deferred-proof-missing: abandoned Git candidate is not preserved")
    material = read_records(root, kind="close-material", task_id=task["id"])
    if not any(row["payload"].get("process") == "abandoned" and row["payload"].get("original_ticket") == original and row["payload"].get("candidate_archive") == archive for row in material):
        raise ChainBroken("long-view-deferred-proof-missing: matching close-material journal is missing")


def _require_deferred_view_receipt(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    from .history import read_records

    _require_preserved_abandon(root, task)
    receipt = task.get("long_view_refresh") or {}
    identity = str(receipt.get("source") or "").rsplit("#", 1)[-1]
    records = read_records(root, kind="long-return-deferred", task_id=task["id"])
    matching = [row for row in records if row["id"] == identity]
    if receipt.get("status") != "deferred" or receipt.get("reason") != "invalid-parent-markdown" or receipt.get("grants_authority") is not False or receipt.get("original_ticket") != task["original_ticket"] or receipt.get("candidate_archive") != task["candidate_archive"] or len(matching) != 1:
        raise ChainBroken("long-view-deferred-proof-missing: explicit matching deferred receipt is missing")
    payload = matching[0]["payload"]
    if payload.get("goal_id") != task["long_goal"]["goal_id"] or payload.get("task_id") != task["id"] or payload.get("process") != "abandoned" or payload.get("issues") != receipt.get("issues") or payload.get("original_ticket") != task["original_ticket"] or payload.get("candidate_archive") != task["candidate_archive"] or payload.get("grants_authority") is not False:
        raise ChainBroken("long-view-deferred-proof-missing: deferred journal does not match preserved facts")
    return receipt


def refresh_long_views(root: Path, task: dict[str, Any], *, preview: bool = False) -> dict[str, Any] | None:
    """Publish genuine recorded lifecycle facts, never grant construction authority."""
    binding = task.get("long_goal")
    if not binding:
        return
    from . import long_tasks

    goal = long_tasks.read_goal(root, binding["goal_id"])
    if goal.get("format") != "markdown":
        return
    if goal.get("issues") and task.get("process") == "abandoned":
        return _require_deferred_view_receipt(root, task)
    long_tasks.apply_operation(root, binding["goal_id"], {"type": "refresh_views", "task_id": task["id"]}, goal["revision"], source={"kind": "ag-task-timeline", "ref": "task:" + task["id"]})
    from .long_authorization import recorded
    if preview and not recorded(task):
        fresh = new_long_binding(root, binding["goal_id"], result_ids=binding["result_ids"], contribution=binding["contribution"], pending=bool(binding.get("proposal_ids")))
        if long_goal_link(fresh) != task.get("goal_link"):
            raise ChainBroken("long-intent-revision-changed: lifecycle view refresh cannot change reviewed intent")
        binding["document_sha256"] = fresh["document_sha256"]
        binding["preview_token"] = fresh["preview_token"]
        from .loop import save_task
        save_task(project_key(root), task)


def record_long_authorization(root: Path, task: dict[str, Any]) -> None:
    from . import long_tasks

    binding = task["long_goal"]
    long_tasks.record_authorization(root, binding["goal_id"], task_id=task["id"], intent_revision=binding["intent_revision"], proposal_ids=binding.get("proposal_ids") or [], preview_token=binding["preview_token"], authorization={"intent_identity": task["intent_identity"]})
    goal = long_tasks.read_goal(root, binding["goal_id"])
    if goal.get("format") == "markdown":
        original = task.get("original_ticket") or {}
        existing = Path(goal["document_path"]).parent / "tickets" / task["id"] / "intent.md"
        text = str(task.get("anchor_preview") or "")
        if not existing.is_file() or existing.read_text(encoding="utf-8") == text:
            long_tasks.archive_ticket(root, binding["goal_id"], task["id"], text, source_path=str(original.get("path") or ""))
        else:
            _link_long_original(root, task, label="Reviewed intent revision; earlier approved original remains immutable")


def _link_long_original(root: Path, task: dict[str, Any], *, label: str) -> None:
    """Index an immutable original through the ordinary fact API, without approval."""
    from . import long_tasks

    original = task.get("original_ticket") or {}
    if not original.get("path"):
        raise ChainBroken("ticket-archive-missing: preserve original before indexing")
    binding = task["long_goal"]
    goal = long_tasks.read_goal(root, binding["goal_id"])
    identity = "original-" + task["id"] + "-" + original["sha256"][:16]
    if any(row.get("id") == identity for row in goal.get("facts", [])):
        return
    relative = os.path.relpath(original["path"], Path(goal["document_path"]).parent).replace("\\", "/")
    long_tasks.apply_operation(root, binding["goal_id"], {"type": "add_fact", "id": identity, "text": f"{label}: child {task['id']} - [Original Markdown]({relative}) - SHA256 `{original['sha256']}`", "result_ids": binding["result_ids"]}, goal["revision"], source={"kind": "ag-child-original", "ref": original["path"]})


def record_long_close(root: Path, task: dict[str, Any], *, process: str, product: str) -> None:
    from . import long_tasks

    binding = task["long_goal"]
    goal = long_tasks.read_goal(root, binding["goal_id"])
    if process == "abandoned" and goal.get("issues"):
        # Closing a preserved candidate cannot grant authority. A malformed
        # parent must remain untouched and must not strand a never-approved
        # worktree merely because its ordinary return index cannot be edited.
        from .history import append_fact
        _require_preserved_abandon(root, task)
        reference = append_fact(root, "long-return-deferred", task["id"], {"goal_id": binding["goal_id"], "task_id": task["id"], "process": process, "issues": goal["issues"], "original_ticket": task["original_ticket"], "candidate_archive": task["candidate_archive"], "grants_authority": False})
        task["long_view_refresh"] = {"status": "deferred", "reason": "invalid-parent-markdown", "issues": goal["issues"], "original_ticket": task["original_ticket"], "candidate_archive": task["candidate_archive"], "grants_authority": False, "source": reference}
        from .loop import save_task
        save_task(project_key(root), task)
        return
    matches = [row for row in goal.get("iterations", []) if row.get("task_id") == task["id"]]
    if process == "abandoned" and not matches:
        # Closing an unapproved draft is a return, never an authorization or an
        # iteration binding. The actual candidate and child original are already
        # durable in close-material and the task timeline before cleanup.
        from .history import append_fact
        append_fact(root, "long-unconfirmed-return", task["id"], {"goal_id": binding["goal_id"], "task_id": task["id"], "process": process, "product": product, "original_ticket": task.get("original_ticket"), "candidate_archive": task.get("candidate_archive"), "grants_authority": False})
        if goal.get("format") == "markdown":
            _link_long_original(root, task, label="Abandoned unconfirmed child; candidate preserved in AG history; no authorization or completed contribution")
            fresh = long_tasks.read_goal(root, binding["goal_id"])
            return_to = binding.get("return_to") or {"result_id": binding["result_ids"][0]}
            label = next((row["text"] for row in fresh["results"] if row["id"] == return_to["result_id"]), binding["contribution"])
            long_tasks.apply_operation(root, binding["goal_id"], {"type": "set_position", "result_id": return_to["result_id"], "current": "本轮已放弃：" + binding["contribution"] + "；候选和原票已保全，尚未开始施工。", "blocker": "仍有未完成承诺" if fresh["remaining"] else "无", "next": "返回：" + label}, fresh["revision"], source={"kind": "ag-unconfirmed-return", "ref": "task:" + task["id"]})
        return
    long_tasks.record_iteration(root, binding["goal_id"], task_id=task["id"], contribution=binding["contribution"], process=process, product=product, return_to=binding.get("return_to"), evidence=task.get("verify") or {})
    if goal.get("format") == "markdown":
        from .ticket_doc import require_ticket, ticket_path
        long_tasks.archive_ticket(root, binding["goal_id"], task["id"], require_ticket(root), source_path=str(ticket_path(root)), phase=process)
        fresh = long_tasks.read_goal(root, binding["goal_id"])
        return_to = binding.get("return_to") or {"result_id": binding["result_ids"][0]}
        label = next((row["text"] for row in fresh["results"] if row["id"] == return_to["result_id"]), binding["contribution"])
        if process == "abandoned":
            current = "本轮已放弃：" + binding["contribution"] + "；候选和原票已保全。"
        elif product == "passed":
            current = "本轮已交付：" + binding["contribution"] + ("；长票尚需核对剩余结果。" if fresh["remaining"] else "；长票全部完成标准待最后核对。")
        else:
            current = "本轮已结束：" + binding["contribution"] + "；交付结果尚未声明通过。"
        long_tasks.apply_operation(root, binding["goal_id"], {"type": "set_position", "result_id": return_to["result_id"], "current": current, "blocker": "仍有未完成承诺" if fresh["remaining"] else "无", "next": "返回：" + label if fresh["remaining"] else "核对整张长票的完成标准与真实证据。"}, fresh["revision"], source={"kind": "ag-child-return", "ref": "task:" + task["id"]})
