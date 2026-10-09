"""Generic subagent file contracts. Adapters are optional and vendor-neutral."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

TASK_SCHEMA = "ag.worker.task.v1"
RESULT_SCHEMA = "ag.worker.result.v1"
ALLOWED_STATUSES = {"done", "blocked", "partial"}


def worker_dir(worktree: Path, worker_id: str = "") -> Path:
    worker_id = worker_id.strip() or f"w-{uuid.uuid4().hex[:8]}"
    return worktree / ".ag-artifacts" / "workers" / worker_id


def create_task(
    *,
    worktree: Path,
    portrait: str,
    anchors: list[dict[str, Any]],
    write_allow: list[str] | None = None,
    worker_id: str = "",
    intent_map_path: str = "",
    anchor_preview: str = "",
    guards: list[str] | None = None,
    defaults: list[str] | None = None,
) -> dict[str, Any]:
    if not str(portrait or "").strip():
        raise ValueError("worker task requires a portrait")
    if not anchors:
        raise ValueError("worker task requires task anchors")

    directory = worker_dir(worktree, worker_id)
    task_id = directory.name
    dossier: dict[str, Any] = {
        "schema": TASK_SCHEMA,
        "task_id": task_id,
        "worktree": str(worktree.resolve()),
        "portrait": str(portrait),
        "anchors": [dict(item) for item in anchors if isinstance(item, dict)],
        "write_allow": [str(item) for item in (write_allow or []) if str(item).strip()],
        "do_not": [
            "run ag finish",
            "merge into canonical",
            "modify anchors or verification gates",
            "claim acceptance",
        ],
        "intent_map_path": intent_map_path,
        "anchor_preview": anchor_preview,
        "guards": [str(item) for item in (guards or []) if str(item).strip()],
        "defaults": [str(item) for item in (defaults or []) if str(item).strip()],
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "task.json").write_text(json.dumps(dossier, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prompt = [
        "# AG Worker Task",
        "",
        f"Work only in: `{worktree}`",
        "",
        "## Portrait",
        portrait.strip(),
        "",
        "## Intent map",
        f"- SVG: `{intent_map_path}`",
        "",
        "```text",
        anchor_preview.strip(),
        "```",
        "",
        "## Anchors",
        *[f"- `{item.get('id')}` [{item.get('kind', 'soft')}]: {item.get('text')}" for item in dossier["anchors"]],
        "## Guards",
        *[f"- {item}" for item in dossier["guards"]],
        "## Defaults",
        *[f"- {item}" for item in dossier["defaults"]],
        "",
        "## Boundaries",
        *[f"- Do not {item.removeprefix('run ')}." for item in dossier["do_not"]],
        "",
        "## Delivery",
        "Write `result.json` beside `task.json` using schema `ag.worker.result.v1`.",
        "Report evidence and open questions; do not claim AG acceptance.",
    ]
    (directory / "TASK.md").write_text("\n".join(prompt) + "\n", encoding="utf-8")
    return {**dossier, "task_path": str((directory / "task.json").resolve()), "prompt_path": str((directory / "TASK.md").resolve())}


def read_result(worktree: Path, worker_id: str) -> dict[str, Any]:
    path = worker_dir(worktree, worker_id) / "result.json"
    if not path.is_file():
        raise FileNotFoundError(f"worker result not found: {path}")
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid worker result JSON: {path}") from exc
    if not isinstance(blob, dict):
        raise ValueError(f"worker result must be a JSON object: {path}")

    errors: list[str] = []
    if blob.get("schema") != RESULT_SCHEMA:
        errors.append("schema must be ag.worker.result.v1")
    if blob.get("task_id") != worker_id:
        errors.append("task_id does not match worker directory")
    if blob.get("status") not in ALLOWED_STATUSES:
        errors.append("status must be done, blocked, or partial")
    for field in ("changed_files", "evidence", "anchor_receipt", "open_questions"):
        if not isinstance(blob.get(field), list):
            errors.append(f"{field} must be a list")
    if errors:
        raise ValueError("; ".join(errors))

    blob["result_path"] = str(path.resolve())
    return blob
