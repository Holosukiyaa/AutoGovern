"""交货 lane. The only lane that may set product or refuse finish."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .loop import abandon, enroll, finish, start, status, unenroll, verify

ID = "ship"
JOB = "交货"
SETS_PRODUCT = True
MAY_REFUSE_FINISH = True
TOOLS = [
    {
        "name": "ag_status",
        "description": "Read-only hook, canonical dirty state, and task-bound delivery facts. Diagnostics are explicit via ag_see. Confirmation is performed by the user in their own terminal; AI hands over the confirm-map command. human-console-required, human-code-mismatch and authorization-unproven explain refusal.",
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
        "description": "Open the draft/ ticket package (ticket.md, spec.json, checks/). Validate results and coverage, seal exact bytes and run target-red/guard-green baselines before independent review. continuation_of comes only from spec.json. Each ticket requires the user to run confirm-map in their own terminal. AI must hand over the command and wait; human-console-required, human-code-mismatch and authorization-unproven explain refusal.",
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
                "contribution": {"type": "string"},
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
    {"name": "ag_andon", "description": "Pull andon with a nonempty reason; freezes the active site.", "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}, "reason": {"type": "string", "minLength": 1}}, "required": ["root", "reason"]}},
    {"name": "ag_handoff", "description": "Write an objective handoff including site facts and a prompt for the next session.", "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}}, "required": ["root"]}},
    {"name": "ag_backbrief", "description": "Resume existing proven authority after matching the actual out_of_scope list, goal (20+ characters) and next action.", "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}, "out_of_scope": {"type": "array", "items": {"type": "string"}}, "goal": {"type": "string", "minLength": 20}, "next": {"type": "string", "minLength": 1}}, "required": ["root", "out_of_scope", "goal", "next"]}},
    {"name": "ag_delivery", "description": "Read-only task facts for active or archived task_id; no installation, diagnosis, migration or authorization.", "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}, "task_id": {"type": "string"}}, "required": ["root"]}},
])


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(str(args.get("root") or "")).expanduser()
    if name in {"ag_andon", "ag_handoff", "ag_backbrief"}:
        from . import site
        if name == "ag_andon":
            return site.andon(root, args.get("reason"))
        if name == "ag_handoff":
            return site.handoff(root)
        return site.backbrief(root, args)
    if name == "ag_status":
        return status(root)
    if name == "ag_delivery":
        from .delivery import build_delivery_snapshot

        return build_delivery_snapshot(root, str(args.get("task_id") or ""))
    if name == "ag_enroll":
        raw = args.get("test_argv")
        test_argv = [str(x) for x in raw] if isinstance(raw, list) else None
        return enroll(root, test_argv=test_argv, note=str(args.get("note") or ""))
    if name == "ag_start":
        from .managed import ChainBroken

        for parameter in ("ticket_type", "goal_id", "long_file", "result_ids"):
            value = args.get(parameter)
            if value and (parameter != "ticket_type" or value != "single"):
                raise ChainBroken(f"long-ticket-retired: ag_start parameter {parameter} is retired")
        if args.get("continuation_of"):
            raise ChainBroken("spec-invalid: continuation_of must come from draft/spec.json")
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
            contribution=str(args.get("contribution") or ""),
        )
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
