"""Switch seat: the finish gate. Critic is the layer before this."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .critic import (
    _configured,
    _item_status,
    complete_chat,
    load_config,
    pack,
    parse_verdict,
    same_family,
    verdict_problems,
)
from .managed import ChainBroken, ag_home, project_key, real_root
from .store import insert_switch_event

RUN_SCHEMA = "ag.switch-run.v1"
PROMPT_NAME = "switch_prompt.md"
PROMPT_VERSION = "ag.switch.v1"
REPORT_NAME = "switch-last.json"
LOG_NAME = "switch.jsonl"

TOOLS = [
    {
        "name": "ag_switch_run",
        "description": (
            "One switch chat on the exam pack. This is the finish gate. "
            "Rejected or unavailable refuse finish. Critic does not."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "exam": {"type": "string"},
                "exam_file": {"type": "string"},
                "base": {"type": "string"},
                "head": {"type": "string"},
            },
            "required": ["root"],
        },
    },
]


def prompt_path() -> Path:
    return Path(__file__).with_name(PROMPT_NAME)


def prompt_text() -> str:
    path = prompt_path()
    if not path.is_file():
        raise ChainBroken(f"missing {PROMPT_NAME}")
    return path.read_text(encoding="utf-8")


def report_path(root: Path) -> Path:
    return ag_home() / "projects" / project_key(real_root(root)) / REPORT_NAME


def log_path(root: Path) -> Path:
    return ag_home() / "projects" / project_key(real_root(root)) / LOG_NAME


def _sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _trim_items(items: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(items, list):
        return out
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "name": str(item.get("name") or ""),
                "status": str(item.get("status") or ""),
                "evidence": str(item.get("evidence") or ""),
                "comment": str(item.get("comment") or ""),
            }
        )
    return out


def append_log(
    root: Path,
    *,
    outcome: str,
    reason: str,
    configured: bool,
    prompt_version: str = PROMPT_VERSION,
    store: str = "",
    exam: str = "",
    pack_blob: dict[str, Any] | None = None,
    items: Any = None,
    task_id: str = "",
    model: str = "",
    probe_red: list[str] | None = None,
    allow_same_family: bool = False,
    thinking: str = "",
    timings: dict[str, Any] | None = None,
) -> str:
    try:
        row: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "outcome": outcome,
            "reason": reason,
            "configured": bool(configured),
            "prompt_version": prompt_version or PROMPT_VERSION,
            "store": store,
            "exam_sha256": _sha256_text(exam),
            "pack_sha256": _sha256_text(json.dumps(pack_blob, ensure_ascii=False, sort_keys=True)) if pack_blob is not None else "",
            "items": _trim_items(items),
        }
        if task_id:
            row["task_id"] = task_id
        if model:
            row["model"] = model
        if probe_red:
            row["probe_red"] = [str(item) for item in probe_red if str(item)]
        if allow_same_family:
            row["allow_same_family"] = True
        if thinking:
            row["thinking"] = str(thinking)[:20000]
        if timings:
            row["timings"] = timings
        path = log_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            row_id = insert_switch_event(root, row)
            report_id = f"sw-{row_id}" if row_id else ""
        except Exception:
            report_id = "sw-" + _sha256_text(row["ts"] + row["outcome"] + row.get("exam_sha256", ""))[:12]
        if report_id:
            row["report_id"] = report_id
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return report_id
    except OSError:
        return ""


def _write_report(root: Path, blob: dict[str, Any]) -> str:
    path = report_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path)


def _result(
    root: Path,
    *,
    outcome: str,
    reason: str,
    pack_blob: dict[str, Any],
    items: list[Any] | None = None,
    summary: str = "",
    model: str | None = None,
    configured: bool = False,
    exam: str = "",
    task_id: str = "",
    probe_red: list[str] | None = None,
    allow_same_family: bool = False,
    thinking: str = "",
    timings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blob: dict[str, Any] = {
        "schema": RUN_SCHEMA,
        "outcome": outcome,
        "reason": reason,
        "items": list(items or []),
        "summary": summary,
        "prompt_version": PROMPT_VERSION,
        "pack": pack_blob,
        "store": "",
        "configured": bool(configured),
    }
    if model:
        blob["model"] = model
    try:
        blob["store"] = _write_report(root, blob)
    except OSError:
        blob["store"] = ""
    blob["report_id"] = append_log(
        root,
        outcome=outcome,
        reason=reason,
        configured=bool(configured),
        prompt_version=PROMPT_VERSION,
        store=str(blob.get("store") or ""),
        exam=exam,
        pack_blob=pack_blob,
        items=items,
        task_id=task_id,
        model=str(model or ""),
        probe_red=probe_red,
        allow_same_family=bool(allow_same_family),
        thinking=thinking,
        timings=timings,
    )
    return blob


def _user_pack(packed: dict[str, Any], critic: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(packed)
    if isinstance(critic, dict) and critic:
        out["critic"] = {
            "outcome": str(critic.get("outcome") or ""),
            "report_id": str(critic.get("report_id") or ""),
            "reason": str(critic.get("reason") or ""),
        }
    return out


def switch_run(
    root: Path,
    *,
    exam: str | None = None,
    exam_file: str | None = None,
    base: str = "",
    head: str = "",
    tree: Path | None = None,
    task_id: str = "",
    probe_red: list[str] | None = None,
    critic: dict[str, Any] | None = None,
) -> dict[str, Any]:
    packed = _user_pack(
        pack(root, exam=exam, exam_file=exam_file, base=base, head=head, tree=tree),
        critic,
    )
    cfg = load_config(root)
    configured = bool(cfg.get("error") or _configured(cfg))
    extra = {
        "configured": configured,
        "exam": str(packed.get("exam") or ""),
        "task_id": task_id,
        "probe_red": probe_red,
    }
    if cfg.get("error"):
        return _result(root, outcome="unavailable", reason=str(cfg["error"]), pack_blob=packed, **extra)
    if not _configured(cfg):
        return _result(root, outcome="unavailable", reason="not-configured", pack_blob=packed, **extra)
    if same_family(str(cfg.get("model") or ""), str(cfg.get("worker_model") or "")):
        if not cfg.get("allow_same_family"):
            return _result(
                root,
                outcome="unavailable",
                reason="andersen: same family",
                pack_blob=packed,
                model=str(cfg.get("model") or ""),
                **extra,
            )
        extra["allow_same_family"] = True
    messages = [
        {"role": "system", "content": prompt_text()},
        {"role": "user", "content": json.dumps(packed, ensure_ascii=False)},
    ]
    run_cfg = dict(cfg)
    try:
        content, reasoning = complete_chat(run_cfg, messages)
        extra["thinking"] = reasoning
    except RuntimeError as exc:
        return _result(
            root,
            outcome="unavailable",
            reason=str(exc),
            pack_blob=packed,
            model=str(cfg.get("model") or ""),
            **extra,
        )
    verdict: dict[str, Any] | None = None
    parse_error: ValueError | None = None
    for blob in (content, reasoning):
        if not str(blob or "").strip():
            continue
        try:
            verdict = parse_verdict(blob)
            break
        except ValueError as exc:
            parse_error = exc
    if verdict is None:
        return _result(
            root,
            outcome="unavailable",
            reason=f"void: {parse_error or 'switch output is not JSON'} (作废)",
            pack_blob=packed,
            model=str(cfg.get("model") or ""),
            **extra,
        )
    problems = verdict_problems(verdict)
    items = verdict.get("items") if isinstance(verdict.get("items"), list) else []
    summary = str(verdict.get("summary") or "")
    model = str(cfg.get("model") or "")
    if problems:
        return _result(
            root,
            outcome="unavailable",
            reason="void: " + "; ".join(problems),
            pack_blob=packed,
            items=items,
            summary=summary,
            model=model,
            **extra,
        )
    raw_verdict = str(verdict.get("verdict") or verdict.get("outcome") or "").strip().casefold()
    has_fail = any(isinstance(item, dict) and _item_status(item) == "fail" for item in items)
    if raw_verdict in {"reject", "rejected", "fail", "failed"} or has_fail:
        outcome = "rejected"
    else:
        outcome = "passed"
    return _result(
        root,
        outcome=outcome,
        reason="",
        pack_blob=packed,
        items=items,
        summary=summary,
        model=model,
        **extra,
    )


def record_from_verify(verify: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(verify, dict):
        return {}
    switch = verify.get("switch")
    return switch if isinstance(switch, dict) else {}


def report_id_from_verify(verify: dict[str, Any] | None) -> str:
    return str(record_from_verify(verify).get("report_id") or "").strip()


def block_message(verify: dict[str, Any] | None) -> str:
    if not isinstance(verify, dict) or "exit" not in verify:
        return ""
    switch = record_from_verify(verify)
    rid = report_id_from_verify(verify)
    suffix = f"; report_id={rid}" if rid else ""
    outcome = str(switch.get("outcome") or "").strip().casefold()
    if outcome == "passed":
        return ""
    if not switch:
        return "switch missing; will not deliver"
    if outcome == "rejected":
        return "switch rejected; will not deliver" + suffix
    return "switch unavailable; will not deliver" + suffix


def attach_verify(
    enrolled: Path,
    *,
    worktree: Path,
    portrait: str,
    task_id: str,
    probe_red: list[str],
    critic: dict[str, Any] | None = None,
    tests_failed: bool = False,
) -> dict[str, Any]:
    """One switch pass after critic. Sets the finish gate. Does not write product files."""
    cfg = load_config(enrolled)
    configured = bool(cfg.get("error") or _configured(cfg))
    switch: dict[str, Any] = {
        "outcome": "unavailable",
        "reason": "not-configured",
        "store": "",
        "configured": configured,
    }
    logged = False
    if tests_failed:
        switch["reason"] = "tests-failed"
    elif not str(portrait or "").strip():
        if configured:
            switch["reason"] = str(cfg.get("error") or "no-exam")
    elif configured:
        try:
            raw = switch_run(
                enrolled,
                exam=portrait,
                tree=worktree,
                task_id=task_id,
                probe_red=probe_red,
                critic=critic,
            )
            logged = True
            switch = {
                "outcome": str(raw.get("outcome") or "unavailable"),
                "reason": str(raw.get("reason") or ""),
                "store": str(raw.get("store") or ""),
                "prompt_version": str(raw.get("prompt_version") or ""),
                "configured": True,
                "report_id": str(raw.get("report_id") or ""),
            }
            if raw.get("model"):
                switch["model"] = raw["model"]
        except Exception as exc:
            switch = {
                "outcome": "unavailable",
                "reason": f"failed: {exc}",
                "store": "",
                "configured": True,
            }
    if not logged:
        switch["report_id"] = append_log(
            enrolled,
            outcome=str(switch.get("outcome") or "unavailable"),
            reason=str(switch.get("reason") or ""),
            configured=bool(switch.get("configured")),
            store=str(switch.get("store") or ""),
            exam=portrait,
            task_id=task_id,
            probe_red=probe_red,
        )
    return switch


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(str(args.get("root") or ""))
    common = dict(
        exam=args.get("exam"),
        exam_file=str(args.get("exam_file") or "") or None,
        base=str(args.get("base") or ""),
        head=str(args.get("head") or ""),
    )
    if name == "ag_switch_run":
        return switch_run(root, **common)
    raise ChainBroken(f"see has no tool {name}")
