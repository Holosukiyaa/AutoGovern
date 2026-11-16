"""交货 lane. The only lane that may set product or refuse finish."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .loop import abandon, confirm_map, enroll, finish, start, status, unenroll, verify

ID = "ship"
JOB = "交货"
SETS_PRODUCT = True
MAY_REFUSE_FINISH = True
TOOLS = [
    {
        "name": "ag_status",
        "description": "Read-only hook, canonical dirty state, and task-bound delivery facts. Diagnostics are explicit via ag_see.",
        "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}}, "required": ["root"]},
    },
    {
        "name": "ag_enroll",
        "description": "Register a git checkout, install the canonical-commit hook, optional test argv.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "test_argv": {"type": "array", "items": {"type": "string"}},
                "note": {"type": "string"},
            },
            "required": ["root"],
        },
    },
    {
        "name": "ag_start",
        "description": "Open a worktree. Write only there. The portrait or fixed lines lock the done-state on the map. Attention anchors are the unsettled route. Later status calls do not rewrite the locked lines.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "portrait": {"type": "string"},
                "anchors": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "text": {"type": "string"},
                            "kind": {
                                "type": "string",
                                "enum": ["soft", "hard", "discoverable", "blocking", "defaulted", "avoid", "obsolete"],
                            },
                            "source": {"type": "string"},
                        },
                        "required": ["text"],
                    },
                },
                "fixed": {"type": "array", "items": {"type": "string"}},
                "guards": {"type": "array", "items": {"type": "string"}},
                "defaults": {"type": "array", "items": {"type": "string"}},
                "ticket_type": {"type": "string", "enum": ["single", "long"]},
                "long_file": {"type": "string"},
                "goal_id": {"type": "string"},
                "result_ids": {"type": "array", "items": {"type": "string"}},
                "continuation_of": {"type": "string"},
                "contribution": {"type": "string"},
            },
            "required": ["root"],
        },
    },
    {
        "name": "ag_confirm_map",
        "description": (
            "Human-only confirmation. The user must execute confirm-map themselves; AI must never call it. "
            "Checks current review and intent identity, then returns ready only after actual thaw."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "by": {"type": "string"},
                "preview": {"type": "string"},
            },
            "required": ["root"],
        },
    },
    {
        "name": "ag_verify",
        "description": "Run enrolled tests (if any), probes, critic, then switch; pin git write-tree. product failed is not an MCP error.",
        "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}}, "required": ["root"]},
    },
    {
        "name": "ag_finish",
        "description": "ff-only into canonical if digest matches, hook is on, canonical is clean.",
        "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}}, "required": ["root"]},
    },
    {
        "name": "ag_abandon",
        "description": "Drop the open worktree without merging.",
        "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}}, "required": ["root"]},
    },
    {
        "name": "ag_unenroll",
        "description": "Remove the hook and restore the previous hooksPath. Abandon any open task first.",
        "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}}, "required": ["root"]},
    },
]

TOOLS.extend([
    {"name": "ag_delivery", "description": "Read-only task facts for active or archived task_id; no installation, diagnosis, migration or authorization.", "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}, "task_id": {"type": "string"}}, "required": ["root"]}},
    {"name": "ag_route", "description": "Record a route adjustment with its reason. Commitment or hard-boundary changes wait for a user decision; this never grants approval.", "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}, "reason": {"type": "string"}, "requires_decision": {"type": "boolean"}}, "required": ["root", "reason"]}},
    {
        "name": "ag_resume",
        "description": "Prepare the user's explicit decision for all pending change_ids in the same task. Re-seal and independently re-review; preserve history and worktree. Never grants construction authority: requires configured=true independent review passage and then the user's personal confirm-map; unconfigured/unavailable/rejected review remains blocked. Retry failed review with resume; after thaw-failed the user retries confirm-map. Wrong, replayed or partial change identities are refused.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "change_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "uniqueItems": True},
                "decision": {"type": "string", "minLength": 1},
            },
            "required": ["root", "change_ids", "decision"],
        },
    },
])


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(str(args.get("root") or "")).expanduser()
    if name == "ag_long":
        return long_call(root, args)
    if name == "ag_status":
        return status(root)
    if name == "ag_delivery":
        from .delivery import build_delivery_snapshot

        return build_delivery_snapshot(root, str(args.get("task_id") or ""))
    if name == "ag_route":
        from .delivery import record_route

        return record_route(root, str(args.get("reason") or ""), requires_decision=bool(args.get("requires_decision")))
    if name == "ag_resume":
        from .decisions import prepare_resume

        return prepare_resume(root, change_ids=args.get("change_ids"), decision=args.get("decision"))
    if name == "ag_enroll":
        raw = args.get("test_argv")
        test_argv = [str(x) for x in raw] if isinstance(raw, list) else None
        return enroll(root, test_argv=test_argv, note=str(args.get("note") or ""))
    if name == "ag_start":
        raw = args.get("anchors")
        anchors = [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else None
        raw_fixed = args.get("fixed")
        fixed = [str(item) for item in raw_fixed] if isinstance(raw_fixed, list) else None
        raw_guards = args.get("guards")
        guards = [str(item) for item in raw_guards] if isinstance(raw_guards, list) else None
        raw_defaults = args.get("defaults")
        defaults = [str(item) for item in raw_defaults] if isinstance(raw_defaults, list) else None
        return start(
            root,
            portrait=str(args.get("portrait") or ""),
            anchors=anchors,
            guards=guards,
            defaults=defaults,
            fixed=fixed,
            goal_id=str(args.get("goal_id") or ""),
            ticket_type=args.get("ticket_type"),
            long_file=str(args.get("long_file") or ""),
            result_ids=args.get("result_ids"),
            continuation_of=str(args.get("continuation_of") or ""),
            contribution=str(args.get("contribution") or ""),
        )
    if name == "ag_confirm_map":
        return confirm_map(root, by=str(args.get("by") or ""), preview=str(args.get("preview") or ""))
    if name == "ag_verify":
        return verify(root)
    if name == "ag_finish":
        return finish(root)
    if name == "ag_abandon":
        return abandon(root)
    if name == "ag_unenroll":
        return unenroll(root)
    from .managed import ChainBroken

    raise ChainBroken(f"unknown tool {name}")


TOOLS.append({
    "name": "ag_long",
    "description": "Editable Markdown long goal authority; legacy SQLite is read-only and requires explicit migrate. Read/list/history/diff/package/export are read-only. Create/import make an unapproved draft; update applies one revision-checked operation. No action grants construction authority; user personally runs confirm-map with the reviewed preview token.",
    "inputSchema": {"type": "object", "properties": {
        "root": {"type": "string"}, "action": {"type": "string", "enum": ["create", "import", "read", "list", "update", "history", "diff", "package", "export", "migrate", "migration-candidate", "legacy-read", "legacy-history"]},
        "goal_id": {"type": "string"}, "title": {"type": "string"}, "original": {"type": "string"},
        "source": {"type": "object"}, "source_ref": {"type": "string"}, "ticket_file": {"type": "string"},
        "results": {"type": "array", "items": {"type": "object"}}, "constraints": {"type": "array", "items": {"type": "object"}},
        "operation": {"type": "object"}, "expected_revision": {"type": "integer"},
        "expected_document_sha256": {"type": "string"}, "expected_legacy_sha256": {"type": "string"}, "since_revision": {"type": "integer"},
        "result_ids": {"type": "array", "items": {"type": "string"}}, "contribution": {"type": "string"}
    }, "required": ["root", "action"]}
})


def long_call(root: Path, args: dict[str, Any]) -> Any:
    from . import long_tasks

    action = str(args.get("action") or "read")
    goal_id = str(args.get("goal_id") or "")
    if action == "list":
        return long_tasks.list_goals(root)
    if action in {"create", "import"}:
        original = str(args.get("original") or "")
        results, constraints = args.get("results"), args.get("constraints")
        source = args.get("source") or {"kind": "user", "ref": str(args.get("source_ref") or ""), "text": original}
        if action == "import":
            from .ticket_doc import collect_redlines, split_document
            from .loop import parse_anchors

            path = Path(str(args.get("ticket_file") or ""))
            if not path.is_file():
                raise ValueError("legacy-import-missing: explicit ticket file required")
            imported_bytes = path.read_bytes()
            imported_text = imported_bytes.decode("utf-8-sig")
            intent, redlines = split_document(imported_text)
            anchors = parse_anchors(intent)
            if not anchors or not intent.strip():
                raise ValueError("legacy-import-invalid: a ticket with intent anchors is required; historical task remains unchanged")
            results = [{"text": row["text"]} for row in anchors if row.get("kind") != "hard"] or [{"text": intent.strip()}]
            constraints = [{"text": line, "scope": ["*"], "source": {"kind": "legacy-ticket-boundary", "ref": str(path.resolve()), "text": line}} for line in collect_redlines(redlines, anchors)]
            # Keep the exact legacy original as its own immutable Markdown file.
            # Quoting only the displayed intent prevents embedded # headings from
            # being reinterpreted as multiple authority titles.
            from .ticket_doc import preserve_original_ticket
            import hashlib
            saved = preserve_original_ticket(root, "import-" + hashlib.sha256(imported_bytes).hexdigest()[:16], imported_text, raw_bytes=imported_bytes)
            original = "\n".join("> " + line if line else ">" for line in intent.splitlines())
            source = {"kind": "legacy-ticket", "ref": saved["path"]}
        return long_tasks.create_goal(root, str(args.get("title") or ""), original, source, results=results, constraints=constraints, goal_id=goal_id)
    if action in {"legacy-read", "legacy-history"}:
        from . import legacy_long_tasks
        if action == "legacy-history":
            return {"goal_id": goal_id, "format": "legacy-sqlite", "read_only": True, "grants_authority": False, "events": legacy_long_tasks.goal_history(root, goal_id, since_revision=int(args.get("since_revision") or 0))}
        return {**legacy_long_tasks.read_goal(root, goal_id), "format": "legacy-sqlite", "read_only": True, "grants_authority": False}
    if action == "migrate":
        return long_tasks.migrate_goal(root, goal_id, expected_legacy_sha256=args.get("expected_legacy_sha256") or None)
    if action == "migration-candidate":
        return long_tasks.migration_candidate(root, goal_id)
    if action == "read":
        return long_tasks.read_goal(root, goal_id)
    if action == "update":
        if type(args.get("expected_revision")) is not int or not isinstance(args.get("operation"), dict):
            raise ValueError("long-update-invalid: expected_revision and one operation required")
        operation = dict(args["operation"])
        if args.get("expected_document_sha256"):
            operation["expected_document_sha256"] = args["expected_document_sha256"]
        return long_tasks.apply_operation(root, goal_id, operation, args["expected_revision"], source=args.get("source") or {"kind": "cli-mcp", "ref": goal_id, "text": "Incremental operation through AG"})
    if action == "history":
        return long_tasks.goal_history(root, goal_id, since_revision=int(args.get("since_revision") or 0))
    if action == "diff":
        return long_tasks.goal_diff(root, goal_id, int(args.get("since_revision") or 0))
    if action == "package":
        return long_tasks.work_package(root, goal_id, args.get("result_ids") or args.get("result_id") or None, contribution=str(args.get("contribution") or ""))
    if action == "export":
        goal = long_tasks.read_goal(root, goal_id)
        if goal.get("format") == "markdown":
            path = Path(goal["document_path"])
            return {"goal_id": goal_id, "authority": "markdown", "document_path": str(path), "editable": True, "markdown": path.read_text(encoding="utf-8"), "document_sha256": goal["document_sha256"]}
        return {"goal_id": goal_id, "authority": "legacy-sqlite", "editable": False, "migration_required": True, "markdown": long_tasks.migration_candidate(root, goal_id)["markdown"]}
    raise ValueError(f"unknown long goal action: {action}")
