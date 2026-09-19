"""One LLM seat runner for critic and switch. Prompts stay in their own md files."""
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
from .store import append_llm_log

SEATS: dict[str, dict[str, Any]] = {
    "critic": {
        "schema": "ag.critic-run.v1",
        "prompt_version": "ag.critic.v1",
        "prompt_name": "critic_prompt.md",
        "report": "critic-last.json",
        "table": "critic_event",
        "void_who": "critic",
        "live": True,
    },
    "switch": {
        "schema": "ag.switch-run.v1",
        "prompt_version": "ag.switch.v1",
        "prompt_name": "switch_prompt.md",
        "report": "switch-last.json",
        "table": "switch_event",
        "void_who": "switch",
        "live": False,
    },
}


def _spec(kind: str) -> dict[str, Any]:
    spec = SEATS.get(kind)
    if not spec:
        raise ChainBroken(f"unknown seat {kind}")
    return spec


def prompt_text(kind: str) -> str:
    spec = _spec(kind)
    path = Path(__file__).with_name(str(spec["prompt_name"]))
    if not path.is_file():
        raise ChainBroken(f"missing {spec['prompt_name']}")
    return path.read_text(encoding="utf-8")


def report_path(kind: str, root: Path) -> Path:
    spec = _spec(kind)
    return ag_home() / "projects" / project_key(real_root(root)) / str(spec["report"])


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


def _user_pack(packed: dict[str, Any], critic: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(packed)
    if isinstance(critic, dict) and critic:
        out["critic"] = {
            "outcome": str(critic.get("outcome") or ""),
            "report_id": str(critic.get("report_id") or ""),
            "reason": str(critic.get("reason") or ""),
        }
    return out


def append_log(
    kind: str,
    root: Path,
    *,
    outcome: str,
    reason: str,
    configured: bool,
    store: str = "",
    exam: str = "",
    pack: dict[str, Any] | None = None,
    items: Any = None,
    task_id: str = "",
    model: str = "",
    probe_red: list[str] | None = None,
    allow_same_family: bool = False,
    thinking: str = "",
    timings: dict[str, Any] | None = None,
    prompt_version: str = "",
) -> str:
    spec = _spec(kind)
    try:
        row: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "outcome": outcome,
            "reason": reason,
            "configured": bool(configured),
            "prompt_version": prompt_version or str(spec["prompt_version"]),
            "store": store,
            "exam_sha256": _sha256_text(exam),
            "pack_sha256": _sha256_text(json.dumps(pack, ensure_ascii=False, sort_keys=True)) if pack is not None else "",
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
        return append_llm_log(root, str(spec["table"]), row)
    except OSError:
        return ""


def _write_report(kind: str, root: Path, blob: dict[str, Any]) -> str:
    path = report_path(kind, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path)


def seat_result(
    kind: str,
    root: Path,
    *,
    outcome: str,
    reason: str,
    pack: dict[str, Any],
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
    spec = _spec(kind)
    blob: dict[str, Any] = {
        "schema": spec["schema"],
        "outcome": outcome,
        "reason": reason,
        "items": list(items or []),
        "summary": summary,
        "prompt_version": spec["prompt_version"],
        "pack": pack,
        "store": "",
        "configured": bool(configured),
    }
    if model:
        blob["model"] = model
    try:
        blob["store"] = _write_report(kind, root, blob)
    except OSError:
        blob["store"] = ""
    blob["report_id"] = append_log(
        kind,
        root,
        outcome=outcome,
        reason=reason,
        configured=bool(configured),
        store=str(blob.get("store") or ""),
        exam=exam,
        pack=pack,
        items=items,
        task_id=task_id,
        model=str(model or ""),
        probe_red=probe_red,
        allow_same_family=bool(allow_same_family),
        thinking=thinking,
        timings=timings,
    )
    return blob


def seat_run(
    kind: str,
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
    spec = _spec(kind)
    packed = pack(root, exam=exam, exam_file=exam_file, base=base, head=head, tree=tree)
    if kind == "switch":
        packed = _user_pack(packed, critic)
    cfg = load_config(root)
    configured = bool(cfg.get("error") or _configured(cfg))
    extra: dict[str, Any] = {
        "configured": configured,
        "exam": str(packed.get("exam") or ""),
        "task_id": task_id,
        "probe_red": probe_red,
    }

    def finish(**kwargs: Any) -> dict[str, Any]:
        merged = dict(extra)
        merged.update(kwargs)
        return seat_result(kind, root, pack=packed, **merged)

    if cfg.get("error"):
        return finish(outcome="unavailable", reason=str(cfg["error"]))
    if not _configured(cfg):
        return finish(outcome="unavailable", reason="not-configured")
    if same_family(str(cfg.get("model") or ""), str(cfg.get("worker_model") or "")):
        if not cfg.get("allow_same_family"):
            return finish(outcome="unavailable", reason="andersen: same family", model=str(cfg.get("model") or ""))
        extra["allow_same_family"] = True
    messages = [
        {"role": "system", "content": prompt_text(kind)},
        {"role": "user", "content": json.dumps(packed, ensure_ascii=False)},
    ]
    held = {"r": "", "c": ""}

    def on_delta(reasoning_text: str, content_text: str) -> None:
        held["r"] = reasoning_text
        held["c"] = content_text
        if not spec["live"]:
            return
        try:
            from .gui import write_live

            write_live(root, phase="critic", thinking=reasoning_text, content=content_text)
        except Exception:
            pass

    run_cfg = dict(cfg)
    if spec["live"]:
        run_cfg["on_delta"] = on_delta
    try:
        content, reasoning = complete_chat(run_cfg, messages)
        extra["thinking"] = (held["r"] or reasoning) if spec["live"] else reasoning
    except RuntimeError as exc:
        return finish(outcome="unavailable", reason=str(exc), model=str(cfg.get("model") or ""))
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
        return finish(
            outcome="unavailable",
            reason=f"void: {parse_error or spec['void_who'] + ' output is not JSON'} (作废)",
            model=str(cfg.get("model") or ""),
        )
    problems = verdict_problems(verdict)
    items = verdict.get("items") if isinstance(verdict.get("items"), list) else []
    summary = str(verdict.get("summary") or "")
    model = str(cfg.get("model") or "")
    if problems:
        return finish(
            outcome="unavailable",
            reason="void: " + "; ".join(problems),
            items=items,
            summary=summary,
            model=model,
        )
    raw_verdict = str(verdict.get("verdict") or verdict.get("outcome") or "").strip().casefold()
    has_fail = any(isinstance(item, dict) and _item_status(item) == "fail" for item in items)
    if raw_verdict in {"reject", "rejected", "fail", "failed"} or has_fail:
        outcome = "rejected"
    else:
        outcome = "passed"
    return finish(outcome=outcome, reason="", items=items, summary=summary, model=model)


def attach_verify(
    kind: str,
    enrolled: Path,
    *,
    worktree: Path,
    portrait: str,
    task_id: str,
    probe_red: list[str],
    tests_failed: bool = False,
    critic: dict[str, Any] | None = None,
) -> dict[str, Any] | tuple[dict[str, Any], list[Any]]:
    cfg = load_config(enrolled)
    configured = bool(cfg.get("error") or _configured(cfg))
    blob: dict[str, Any] = {
        "outcome": "unavailable",
        "reason": "not-configured",
        "store": "",
        "configured": configured,
    }
    planted: list[Any] = []
    logged = False
    if tests_failed:
        blob["reason"] = "tests-failed"
    elif not str(portrait or "").strip():
        if configured:
            blob["reason"] = str(cfg.get("error") or "no-exam")
    elif configured:
        try:
            raw = seat_run(
                kind,
                enrolled,
                exam=portrait,
                tree=worktree,
                task_id=task_id,
                probe_red=probe_red,
                critic=critic,
            )
            logged = True
            blob = {
                "outcome": str(raw.get("outcome") or "unavailable"),
                "reason": str(raw.get("reason") or ""),
                "store": str(raw.get("store") or ""),
                "prompt_version": str(raw.get("prompt_version") or ""),
                "configured": True,
                "report_id": str(raw.get("report_id") or ""),
            }
            if raw.get("model"):
                blob["model"] = raw["model"]
            if kind == "critic" and str(raw.get("outcome") or "") == "rejected":
                from .probe import plant_from_reject

                planted = list(plant_from_reject(enrolled, items=raw.get("items"), tree=worktree) or [])
        except Exception as exc:
            blob = {
                "outcome": "unavailable",
                "reason": f"failed: {exc}",
                "store": "",
                "configured": True,
            }
    if not logged:
        blob["report_id"] = append_log(
            kind,
            enrolled,
            outcome=str(blob.get("outcome") or "unavailable"),
            reason=str(blob.get("reason") or ""),
            configured=bool(blob.get("configured")),
            store=str(blob.get("store") or ""),
            exam=portrait,
            task_id=task_id,
            probe_red=probe_red,
        )
    if kind == "critic":
        return blob, planted
    return blob
