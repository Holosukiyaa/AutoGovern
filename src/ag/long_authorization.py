"""Trace one parent approval and bind reviewed children without inventing a human event."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .delivery import PASS
from .history import digest, read_records
from .managed import ChainBroken
from .store import load_task_timeline, scan_llm_log


def recorded(task: dict[str, Any]) -> bool:
    """Presence only. Construction must additionally validate the live proof."""
    receipt = task.get("long_authorization") or {}
    return bool(task.get("intent_map_confirmed") or (
        task.get("long_goal") and receipt.get("mode") == "inherited-long"
        and receipt.get("task_id") == task.get("id")
        and receipt.get("intent_identity") == task.get("intent_identity")
        and receipt.get("parent_proof")
    ))


def independent_review(root: Path, task: dict[str, Any], document: str) -> None:
    from .authorization import review_identity
    from .ticket_doc import split_document

    review = task.get("ticket_review") or {}
    scan = scan_llm_log(root, "ticket_event")
    if scan["bad_lines"] or any(task["id"] in {row.get("task_id"), row.get("expected_task_id")} for row in scan["diagnostics"]):
        raise ChainBroken("long-authorization-review-conflict: independent review history is invalid")
    rows = [row for row in scan["rows"] if row.get("task_id") == task["id"] and row.get("report_id") == review.get("report_id")]
    body, _ = split_document(document)
    expected = review_identity(body, str(task.get("portrait") or ""), list(task.get("anchors") or []), list(task.get("redlines") or []), task.get("goal_link"))
    if (review.get("configured") is not True or review.get("outcome") not in PASS
        or not review.get("report_id") or len(rows) != 1 or rows[0].get("configured") is not True or rows[0].get("outcome") not in PASS
        or rows[0].get("review_identity") != expected):
        raise ChainBroken("long-authorization-review-required: a matching independent review of this child and its parent scope is required; retry start")


def parent_proof(root: Path, goal: dict[str, Any]) -> dict[str, Any]:
    """Read historical facts in this project, including closed and rolled-up tasks."""
    from .authorization import _validate_preserved_ticket

    proof = goal.get("authorization") or {}
    if goal.get("format") != "markdown" or goal.get("read_only") or goal.get("issues"):
        raise ChainBroken("long-authorization-parent-invalid: a valid Markdown parent is required")
    if any(row.get("state", row.get("status")) in {"pending", "proposed", "awaiting-decision"} for row in goal.get("decisions", [])):
        raise ChainBroken("await-user-decision: parent intent changes require review and human confirmation")
    if (not proof or not proof.get("task_id") or not proof.get("intent_identity")
        or proof.get("authorization_identity") != proof.get("intent_identity") or not proof.get("preview_token")):
        raise ChainBroken("long-authorization-proof-missing: parent has no traceable original approval")
    if (proof.get("authorized_intent_revision") != goal.get("intent_revision")
        or goal.get("authorized_intent_revision") != goal.get("intent_revision")
        or proof.get("authorized_intent_sha256") != goal.get("intent_sha256")):
        raise ChainBroken("long-intent-revision-changed: parent approval does not cover the current intent")
    task_id = str(proof["task_id"])
    timeline = load_task_timeline(root, task_id)
    if timeline.get("diagnostics"):
        raise ChainBroken("long-authorization-history-conflict: original approval history conflicts")
    steps = timeline["steps"]
    approved, ready = proof.get("approved"), proof.get("ready")
    if (not isinstance(approved, dict) or not isinstance(ready, dict)
        or approved not in steps or ready not in steps
        or approved.get("phase") != "intent-map-confirmed" or not approved.get("by")
        or ready.get("phase") != "worktree-ready"
        or any(row.get("task_id") != task_id or row.get("intent_identity") != proof["intent_identity"] for row in (approved, ready))
        or str(ready.get("ts") or "") < str(approved.get("ts") or "")):
        raise ChainBroken("long-authorization-original-proof-missing: original human confirmation and successful thaw are required")
    snapshots = [row["task"] for row in steps if isinstance(row.get("task"), dict) and row["task"].get("id") == task_id and row["task"].get("intent_identity") == proof["intent_identity"]]
    if not snapshots:
        raise ChainBroken("long-authorization-original-ticket-missing: original reviewed identity is unavailable")
    original = snapshots[-1]
    binding = original.get("long_goal") or {}
    link = original.get("goal_link") or {}
    if (binding.get("goal_id") != goal["goal_id"] or link.get("goal_id") != goal["goal_id"]
        or binding.get("preview_token") != proof["preview_token"]
        or binding.get("preview_intent_sha256", binding.get("intent_sha256")) != goal["intent_sha256"]
        or binding.get("preview_intent_revision", binding.get("intent_revision")) != goal["intent_revision"]
        or (original.get("ticket_review") or {}).get("report_id") != proof.get("report_id")):
        raise ChainBroken("long-authorization-parent-mismatch: original approval belongs to another parent or scope")
    descriptor = original.get("original_ticket") or {}
    documents = [str(original.get("anchor_preview") or "")] + [row["payload"].get("text", "") for row in read_records(root, kind="ticket", task_id=task_id)]
    # Exact original Markdown may be reclaimed into history; it must match the
    # immutable child descriptor and the reviewed identity, not an editable label.
    documents = [text for text in documents if hashlib.sha256(text.encode("utf-8")).hexdigest() == descriptor.get("sha256")]
    if not documents:
        raise ChainBroken("long-authorization-original-ticket-missing: preserved original Markdown is unavailable")
    document = documents[-1]
    if any(row.get("state") == "active" and row.get("text") not in document for name in ("results", "constraints") for row in goal.get(name, [])):
        raise ChainBroken("long-authorization-scope-not-shown: original preview did not include the full parent results and constraints")
    sealed = "\n".join(original.get("redlines") or []) + ("\n" if original.get("redlines") else "")
    _validate_preserved_ticket(root, original, document, sealed)
    independent_review(root, original, document)
    return {"fingerprint": digest({"goal_id": goal["goal_id"], "proof": proof}), "source_task_id": task_id, "proof": proof}


def validate_inherited(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    from .long_tasks import read_goal
    from .ticket_doc import require_ticket

    receipt = task.get("long_authorization") or {}
    binding = task.get("long_goal") or {}
    if not binding or receipt.get("mode") != "inherited-long":
        raise ChainBroken("long-authorization-proof-missing: no inherited child receipt")
    parent = parent_proof(root, read_goal(root, binding["goal_id"]))
    expected = {"mode": "inherited-long", "task_id": task["id"], "intent_identity": task["intent_identity"],
        "goal_id": binding["goal_id"], "parent_proof": parent["fingerprint"], "source_task_id": parent["source_task_id"],
        "report_id": (task.get("ticket_review") or {}).get("report_id"), "result_ids": binding["result_ids"]}
    if receipt != expected or task.get("authorization_identity") != task.get("intent_identity"):
        raise ChainBroken("long-authorization-receipt-mismatch: inherited approval no longer matches this child")
    steps = load_task_timeline(root, task["id"])
    if steps.get("diagnostics") or not any(row.get("phase") == "long-authorization-inherited" and row.get("authorization") == receipt for row in steps["steps"]):
        raise ChainBroken("long-authorization-receipt-missing: inheritance has no matching lifecycle record")
    independent_review(root, task, require_ticket(root))
    return parent


def inherit(root: Path, task: dict[str, Any]) -> bool:
    """Only start calls this writer, after sealing and independent child review."""
    from .authorization import validate_ticket
    from .long_tasks import read_goal
    from .loop import save_task
    from .managed import project_key
    from .store import append_task_step
    from .ticket_doc import require_ticket

    if not task.get("long_goal") or task.get("intent_map_confirmed") or task.get("resume_preparation"):
        return False
    goal = read_goal(root, task["long_goal"]["goal_id"])
    if not goal.get("authorization"):
        return False
    parent = parent_proof(root, goal)
    validate_ticket(root, task)
    independent_review(root, task, require_ticket(root))
    binding = task["long_goal"]
    receipt = {"mode": "inherited-long", "task_id": task["id"], "intent_identity": task["intent_identity"],
        "goal_id": binding["goal_id"], "parent_proof": parent["fingerprint"], "source_task_id": parent["source_task_id"],
        "report_id": task["ticket_review"]["report_id"], "result_ids": binding["result_ids"]}
    if task.get("long_authorization") != receipt:
        append_task_step(root, task["id"], "long-authorization-inherited", authorization=receipt)
        task["long_authorization"] = receipt
        task["authorization_identity"] = task["intent_identity"]
        task["worktree_ready"] = False
        save_task(project_key(root), task)
    return True


def validate_direct(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    """A long child cannot turn its bool into a new human approval."""
    from .long_tasks import read_goal
    parent = parent_proof(root, read_goal(root, task["long_goal"]["goal_id"]))
    proof = parent["proof"]
    if (proof.get("task_id") != task.get("id") or proof.get("intent_identity") != task.get("intent_identity")
        or task.get("authorization_identity") != task.get("intent_identity")
        or proof["approved"].get("by") != task.get("intent_map_confirmed_by")):
        raise ChainBroken("long-authorization-original-proof-missing: this child has no matching personal confirmation; recover inheritance with start")
    return parent


def validate_human_record(root: Path, task: dict[str, Any]) -> None:
    """Retain a genuine first approval while its thaw/parent publication retries."""
    timeline = load_task_timeline(root, task["id"])
    if (not task.get("intent_map_confirmed") or task.get("authorization_identity") != task.get("intent_identity")
        or timeline.get("diagnostics") or not any(
            row.get("phase") == "intent-map-confirmed" and row.get("intent_identity") == task.get("intent_identity")
            and row.get("by") == task.get("intent_map_confirmed_by") and row.get("by")
            for row in timeline["steps"])):
        raise ChainBroken("long-authorization-original-proof-missing: no original personal confirmation matches this child")


def activation_complete(root: Path, task: dict[str, Any]) -> bool:
    """The existing parent iteration is the durable publication boundary."""
    if not task.get("long_goal"):
        return bool(task.get("worktree_ready"))
    from .long_tasks import read_goal
    goal = read_goal(root, task["long_goal"]["goal_id"])
    if not any(row.get("task_id") == task.get("id") and row.get("authorization_identity") == task.get("intent_identity") for row in goal.get("iterations", [])):
        return False
    proof = goal.get("authorization") or {}
    if task.get("long_authorization"):
        receipt = task["long_authorization"]
        return receipt.get("parent_proof") == digest({"goal_id": goal["goal_id"], "proof": proof})
    return proof.get("task_id") == task.get("id") and proof.get("intent_identity") == task.get("intent_identity")
