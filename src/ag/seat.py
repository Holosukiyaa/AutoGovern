"""One LLM seat runner for critic, switch, and ticket. Prompts stay in their own md files."""
from __future__ import annotations

import hashlib
import inspect
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .critic import (
    _EVIDENCE_REF,
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
from .store import append_llm_log, last_llm_event, list_ticket_events, project_dir

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
        "live": True,
    },
    "ticket": {
        "schema": "ag.ticket-run.v1",
        "prompt_version": "ag.ticket.v1",
        "prompt_name": "ticket_prompt.md",
        "report": "ticket-last.json",
        "table": "ticket_event",
        "void_who": "ticket",
        "live": True,
    },
}

_TICKET_DIMS: tuple[str, ...] = ("goal_clarity", "anchor_chain", "redline_focus")
_CLOSURE_RE = re.compile(
    r"(若|如果|当|否则|拒绝|失败|禁止|拦截|不能|不许|错误|异常|未通过|无效|反之|但|而|"
    r"if|when|else|otherwise|reject|refuse|deny|fail|invalid|error|unless)",
    re.IGNORECASE,
)
_PLATITUDE_RE = re.compile(
    r"^(?:保证|确保|保持|注意)?(?:代码质量|高性能|不出\s*bug|不要出\s*bug|不引入\s*bug|"
    r"不要破坏(?:现有|原有)?功能|不影响(?:现有|原有)?功能|代码整洁|写好代码|注意安全|安全第一)"
    r"(?:[，,、；;\s]*(?:保证|确保|保持|注意)?(?:代码质量|高性能|不出\s*bug|不要出\s*bug|不引入\s*bug|"
    r"不要破坏(?:现有|原有)?功能|不影响(?:现有|原有)?功能|代码整洁|写好代码|注意安全|安全第一))*[。！!.\s]*$",
    re.IGNORECASE,
)
_NORM_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def _norm_text(text: str) -> str:
    return _NORM_RE.sub("", str(text or "")).lower()


def _bigram_jaccard(a: str, b: str) -> float:
    na = _norm_text(a)
    nb = _norm_text(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    sa = {na[i : i + 2] for i in range(len(na) - 1)} if len(na) >= 2 else {na}
    sb = {nb[i : i + 2] for i in range(len(nb) - 1)} if len(nb) >= 2 else {nb}
    union = len(sa | sb)
    return (len(sa & sb) / union) if union else 0.0


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
    retried_void: bool = False,
    retried_lazy: bool = False,
    thread_id: str = "",
) -> dict[str, Any]:
    spec = _spec(kind)
    resolved_thread_id = str(
        thread_id
        or (pack.get("thread_id") if isinstance(pack, dict) else "")
        or ((timings or {}).get("thread_id") if isinstance(timings, dict) else "")
        or ""
    )
    merged_timings: dict[str, Any] = dict(timings or {})
    if resolved_thread_id and "thread_id" not in merged_timings:
        merged_timings["thread_id"] = resolved_thread_id
    if retried_void:
        merged_timings["retried_void"] = True
    if retried_lazy:
        merged_timings["retried_lazy"] = True
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
    if resolved_thread_id:
        blob["thread_id"] = resolved_thread_id
    if model:
        blob["model"] = model
    if retried_void:
        blob["retried_void"] = True
    if retried_lazy:
        blob["retried_lazy"] = True
    blob["store"] = str(report_path(kind, root))
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
        timings=merged_timings if merged_timings else None,
    )
    tail = last_llm_event(root, str(spec["table"]))
    if isinstance(tail, dict):
        for key in ("report_id", "ts", "outcome", "reason"):
            if tail.get(key) not in (None, ""):
                blob[key] = tail[key]
    try:
        _write_report(kind, root, blob)
    except OSError:
        pass
    return blob


def _prev_ticket_redlines(repo: Path, task_id: str) -> list[str]:
    from .ticket_doc import previous_redlines, section_lines, split_document

    tid = str(task_id or "").strip()
    t_dir = repo / ".data" / "tickets"
    if t_dir.is_dir():
        candidates = [
            p
            for p in t_dir.glob("*.md")
            if p.is_file() and p.stem.strip() and (not tid or p.stem.strip() != tid)
        ]
        if candidates:
            latest = max(candidates, key=lambda p: p.stat().st_mtime)
            try:
                _, red_body = split_document(latest.read_text(encoding="utf-8"))
                lines = section_lines(red_body)
                if lines:
                    return lines
            except OSError:
                pass
    # Only fall back to .data/redlines.copy if tid was not already sealed into .data/tickets/{tid}.md
    if not (tid and (t_dir / f"{tid}.md").is_file()):
        copied = previous_redlines(repo)
        if copied:
            return copied
    return []


def ticket_prescreen(
    root: Path,
    *,
    intent_body: str = "",
    portrait: str = "",
    anchors: list[dict[str, Any]] | None = None,
    redlines: list[str] | None = None,
    task_id: str = "",
) -> dict[str, Any]:
    """Deterministic 0-token local script pre-screening for startup ticket review."""
    repo = real_root(root)
    tid = str(task_id or "").strip()
    seen_ids: set[str] = set()
    if tid:
        seen_ids.add(tid)
    t_dir = repo / ".data" / "tickets"
    if t_dir.is_dir():
        for p in t_dir.glob("*.md"):
            if p.is_file() and p.stem.strip():
                seen_ids.add(p.stem.strip())
    p_tasks = project_dir(repo) / "tasks"
    if p_tasks.is_dir():
        for p in p_tasks.glob("*.json"):
            if p.is_file() and p.stem.strip():
                seen_ids.add(p.stem.strip())

    prev_goals: list[str] = []
    prev_summaries: list[str] = []
    try:
        events = list_ticket_events(repo, limit=10)
    except Exception:
        events = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        ev_tid = str(ev.get("task_id") or "").strip()
        if ev_tid:
            seen_ids.add(ev_tid)
        if str(ev.get("reason") or "") == "script-prescreen-rejected":
            continue
        if str(ev.get("outcome") or "").strip().casefold() not in {"passed", "pass", "allow"}:
            continue
        timings = ev.get("timings") if isinstance(ev.get("timings"), dict) else {}
        g = str(ev.get("understood_goal") or timings.get("understood_goal") or "").strip()
        s = str(ev.get("summary") or timings.get("summary") or "").strip()
        if g and g not in prev_goals:
            prev_goals.append(g)
        if s and s != "本地通用脚本预筛未通过" and s not in prev_summaries:
            prev_summaries.append(s)
    prev_goals = prev_goals[-3:]
    prev_summaries = prev_summaries[-3:]

    ticket_seq = max(1, len(seen_ids))
    strict_round_mode = ticket_seq >= 3

    clean_redlines = [str(r).strip() for r in (redlines or []) if str(r).strip()]
    prev_redlines = _prev_ticket_redlines(repo, tid)
    overlap = 0.0
    if clean_redlines and prev_redlines:
        prev_norms = {_norm_text(x) for x in prev_redlines if _norm_text(x)}
        hits = 0
        for rl in clean_redlines:
            n_rl = _norm_text(rl)
            if not n_rl:
                continue
            if n_rl in prev_norms or any(_bigram_jaccard(rl, pr) >= 0.85 for pr in prev_redlines):
                hits += 1
        overlap = hits / len(clean_redlines)

    hard_failures: list[str] = []
    warnings: list[str] = []

    combined_text = (str(portrait or "").strip() + "\n" + str(intent_body or "").strip()).strip()
    if len(combined_text) < 20:
        hard_failures.append("portrait:意图描述过短，缺少可理解的业务目标")

    if anchors is None:
        from .loop import parse_anchors

        raw_anchors: list[Any] = parse_anchors(combined_text)
    else:
        raw_anchors = list(anchors)

    active_texts: list[str] = []
    for item in raw_anchors:
        if isinstance(item, dict):
            kind = str(item.get("kind") or "soft").strip().lower()
            if kind in {"avoid", "obsolete"}:
                continue
            txt = str(item.get("text") or "").strip()
        else:
            txt = str(item or "").strip()
        if txt:
            active_texts.append(txt)

    if not active_texts:
        hard_failures.append("portrait:缺少意图锚点（anchor），未锁住行为链路")
    else:
        for txt in active_texts:
            if len(txt) < 18:
                hard_failures.append(f"portrait:{txt} (锚点过短，仅为碎片术语而非完整链路)")
        if not any(_CLOSURE_RE.search(txt) for txt in active_texts):
            hard_failures.append("portrait:意图锚点断链（仅有单向动作，缺少反向/边界拒绝行为闭环）")

    if not clean_redlines:
        hard_failures.append("portrait:缺少红线（## 红线 为空）")
    else:
        for rl in clean_redlines:
            if len(rl) < 10 or _PLATITUDE_RE.match(rl):
                hard_failures.append(f"portrait:{rl} (红线过宽或失焦，属空泛套话)")

    if strict_round_mode and overlap >= 0.9 and clean_redlines:
        warnings.append("连续第3+票红线与前序票高度重合，请严查是否偷懒照搬而未针对本票窄化")

    return {
        "ok": len(hard_failures) == 0,
        "ticket_seq": ticket_seq,
        "strict_round_mode": strict_round_mode,
        "redline_overlap_ratio": round(overlap, 3),
        "hard_failures": hard_failures,
        "warnings": warnings,
        "prev_goals": prev_goals,
        "prev_summaries": prev_summaries,
    }


def _sync_items_from_scores(verdict: dict[str, Any]) -> None:
    scores = verdict.get("scores")
    if not isinstance(scores, dict):
        return
    if isinstance(verdict.get("items"), list) and verdict["items"]:
        return
    synth: list[dict[str, str]] = []
    for dim in _TICKET_DIMS:
        entry = scores.get(dim)
        if not isinstance(entry, dict):
            continue
        st = _item_status(entry)
        raw_score = entry.get("score")
        if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool) and float(raw_score) < 7:
            st = "fail"
        if st not in {"pass", "fail"}:
            st = "pass"
        synth.append(
            {
                "name": dim,
                "status": st,
                "evidence": str(entry.get("evidence") or ""),
                "comment": str(entry.get("comment") or ""),
            }
        )
    if synth:
        verdict["items"] = synth


def ticket_verdict_problems(
    verdict: dict[str, Any],
    prescreen: dict[str, Any],
    portrait: str,
    intent_body: str = "",
) -> tuple[list[str], bool]:
    """Validate 3D ticket review verdict and check for single-round or multi-round laziness."""
    _sync_items_from_scores(verdict)
    problems = verdict_problems(verdict)
    is_lazy = False

    understood_goal = str(verdict.get("understood_goal") or "").strip()
    if len(understood_goal) < 10:
        problems.append("missing or too-short understood_goal")
        is_lazy = True
    else:
        source_text = f"{portrait or ''}\n{intent_body or ''}"
        norm_goal = _norm_text(understood_goal)
        norm_source = _norm_text(source_text)
        copied_sub = len(understood_goal) >= 15 and bool(norm_goal) and (norm_goal in norm_source)
        copied_sim = (
            _bigram_jaccard(understood_goal, portrait) >= 0.85
            or _bigram_jaccard(understood_goal, intent_body) >= 0.85
        )
        if copied_sub or copied_sim:
            problems.append("lazy-review: understood_goal copied from ticket text without independent restatement")
            is_lazy = True

    scores = verdict.get("scores")
    any_dim_fail = False
    all_high_scores = True
    all_short_comments = True

    if not isinstance(scores, dict):
        problems.append("scores must be an object with goal_clarity, anchor_chain, redline_focus")
        all_high_scores = False
        all_short_comments = False
    else:
        for dim in _TICKET_DIMS:
            entry = scores.get(dim)
            if not isinstance(entry, dict):
                problems.append(f"scores.{dim} must be an object")
                all_high_scores = False
                all_short_comments = False
                continue
            raw_score = entry.get("score")
            if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)) or not (0 <= float(raw_score) <= 10):
                problems.append(f"scores.{dim}.score must be 0..10")
                all_high_scores = False
            else:
                num_score = float(raw_score)
                if num_score < 7:
                    any_dim_fail = True
                if num_score < 9:
                    all_high_scores = False
            st = _item_status(entry)
            if st not in {"pass", "fail"}:
                problems.append(f"scores.{dim}.status must be pass|fail")
            elif st == "fail":
                any_dim_fail = True
            comment = str(entry.get("comment") or "").strip()
            if len(comment) < 6:
                problems.append(f"scores.{dim}.comment too short")
                is_lazy = True
            if len(comment) >= 15:
                all_short_comments = False
            evidence = str(entry.get("evidence") or "").strip()
            if st == "fail" and not _EVIDENCE_REF.search(evidence):
                problems.append(f"scores.{dim} fail without portrait:… / path:line evidence (作废)")

    raw_verdict = str(verdict.get("verdict") or verdict.get("outcome") or "").strip().casefold()
    doubts = [str(d).strip() for d in (verdict.get("doubts") or []) if str(d).strip()] if isinstance(verdict.get("doubts"), list) else []
    gc_entry = scores.get("goal_clarity") if isinstance(scores, dict) else None
    gc_fail = isinstance(gc_entry, dict) and _item_status(gc_entry) == "fail"

    if (any_dim_fail or (doubts and gc_fail)) and raw_verdict in {"pass", "passed"}:
        problems.append("dimension score < 7 or status=fail requires verdict=reject")

    prev_goals = (prescreen or {}).get("prev_goals") if isinstance(prescreen, dict) else []

    dup_prior = False
    if understood_goal and isinstance(prev_goals, list):
        for pg in prev_goals:
            if _norm_text(understood_goal) == _norm_text(str(pg)) or _bigram_jaccard(understood_goal, str(pg)) >= 0.85:
                dup_prior = True
                break
    # 固定收尾措辞本身不算偷懒：只有实质重述（understood_goal）也撞往期评审，才判照抄
    if dup_prior:
        problems.append("lazy-review: review summary/goal duplicates a prior ticket review")
        is_lazy = True

    strict_round = bool((prescreen or {}).get("strict_round_mode")) if isinstance(prescreen, dict) else False
    if strict_round and isinstance(scores, dict) and all_high_scores and not doubts and all_short_comments:
        problems.append("lazy-review: round 3+ rubber-stamp high scores without detailed critique or boundary doubts")
        is_lazy = True

    return problems, is_lazy


def ticket_run(
    root: Path,
    *,
    intent_body: str = "",
    portrait: str = "",
    anchors: list[dict[str, Any]] | None = None,
    redlines: list[str] | None = None,
    task_id: str = "",
) -> dict[str, Any]:
    """Run deterministic ticket_prescreen then stateless 1-shot DS 3D semantic review."""
    spec = _spec("ticket")
    repo = real_root(root)
    if not intent_body and not portrait and anchors is None and redlines is None:
        from .loop import parse_anchors
        from .ticket_doc import collect_redlines, split_document, ticket_path

        t_path = ticket_path(repo)
        if t_path.is_file():
            doc = t_path.read_text(encoding="utf-8")
            intent_body, red_body = split_document(doc)
            anchors = parse_anchors(intent_body)
            redlines = collect_redlines(red_body, anchors)
            portrait = intent_body

    if spec["live"]:
        try:
            lpath = project_dir(repo) / "ticket-live.jsonl"
            lpath.parent.mkdir(parents=True, exist_ok=True)
            lpath.write_text("", encoding="utf-8")
        except OSError:
            pass

    thread_id = f"tr-{task_id or 'init'}-{uuid.uuid4().hex[:8]}"
    prescreen = ticket_prescreen(
        repo,
        intent_body=intent_body,
        portrait=portrait,
        anchors=anchors,
        redlines=redlines,
        task_id=task_id,
    )
    clean_redlines = [str(x).strip() for x in (redlines or []) if str(x).strip()]
    packed: dict[str, Any] = {
        "schema": "ag.ticket-pack.v1",
        "thread_id": thread_id,
        "task_id": task_id,
        "portrait": portrait,
        "intent_body": intent_body,
        "anchors": list(anchors or []),
        "redlines": clean_redlines,
        "script_digest": prescreen,
    }
    cfg = load_config(repo)
    configured = bool(cfg.get("error") or _configured(cfg))
    exam_text = str(portrait or intent_body or "")

    def _enrich(
        blob: dict[str, Any],
        *,
        understood_goal: str = "",
        doubts: list[str] | None = None,
        scores: dict[str, Any] | None = None,
        retried_lazy: bool = False,
    ) -> dict[str, Any]:
        blob["thread_id"] = thread_id
        blob["script_digest"] = prescreen
        blob["understood_goal"] = understood_goal
        blob["doubts"] = list(doubts or [])
        blob["scores"] = dict(scores or {})
        blob["retried_lazy"] = bool(retried_lazy)
        try:
            blob["store"] = _write_report("ticket", repo, blob)
        except OSError:
            pass
        return blob

    if not prescreen["ok"]:
        items = [
            {
                "name": "script_prescreen",
                "status": "fail",
                "evidence": hf if _EVIDENCE_REF.search(hf) else f"portrait:{hf}",
                "comment": hf,
            }
            for hf in prescreen["hard_failures"]
        ]
        res = seat_result(
            "ticket",
            repo,
            outcome="rejected",
            reason="script-prescreen-rejected",
            pack=packed,
            items=items,
            summary="本地通用脚本预筛未通过",
            configured=configured,
            exam=exam_text,
            task_id=task_id,
            timings={
                "script_short_circuit": True,
                "thread_id": thread_id,
                "ticket_seq": prescreen["ticket_seq"],
            },
            thread_id=thread_id,
        )
        return _enrich(res, doubts=list(prescreen["hard_failures"]))

    if cfg.get("error"):
        res = seat_result(
            "ticket",
            repo,
            outcome="unavailable",
            reason=str(cfg["error"]),
            pack=packed,
            configured=configured,
            exam=exam_text,
            task_id=task_id,
            timings={"thread_id": thread_id, "ticket_seq": prescreen["ticket_seq"]},
            thread_id=thread_id,
        )
        return _enrich(res)
    if not _configured(cfg):
        res = seat_result(
            "ticket",
            repo,
            outcome="unavailable",
            reason="not-configured",
            pack=packed,
            configured=configured,
            exam=exam_text,
            task_id=task_id,
            timings={"thread_id": thread_id, "ticket_seq": prescreen["ticket_seq"]},
            thread_id=thread_id,
        )
        return _enrich(res)

    allow_same = False
    model = str(cfg.get("model") or "")
    if same_family(model, str(cfg.get("worker_model") or "")):
        if not cfg.get("allow_same_family"):
            res = seat_result(
                "ticket",
                repo,
                outcome="unavailable",
                reason="andersen: same family",
                pack=packed,
                configured=configured,
                exam=exam_text,
                task_id=task_id,
                model=model,
                timings={"thread_id": thread_id, "ticket_seq": prescreen["ticket_seq"]},
                thread_id=thread_id,
            )
            return _enrich(res)
        allow_same = True

    messages = [
        {"role": "system", "content": prompt_text("ticket")},
        {"role": "user", "content": json.dumps(packed, ensure_ascii=False)},
    ]
    held = {"r": "", "c": ""}

    def live_log(reasoning_text: str, content_text: str) -> None:
        try:
            path = project_dir(repo) / "ticket-live.jsonl"
            row = {
                "schema": "ag.ticket-live.v1",
                "task_id": task_id,
                "thread_id": thread_id,
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                "reasoning": str(reasoning_text)[-12000:],
                "content": str(content_text)[-12000:],
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()
        except Exception:
            pass

    def on_delta(reasoning_text: str, content_text: str) -> None:
        held["r"] = reasoning_text
        held["c"] = content_text
        live_log(reasoning_text, content_text)

    run_cfg = dict(cfg)
    if spec["live"]:
        run_cfg["on_delta"] = on_delta
    try:
        content, reasoning = complete_chat(run_cfg, messages)
        thinking = (held["r"] or reasoning) if spec["live"] else reasoning
    except RuntimeError as exc:
        res = seat_result(
            "ticket",
            repo,
            outcome="unavailable",
            reason=str(exc),
            pack=packed,
            configured=configured,
            exam=exam_text,
            task_id=task_id,
            model=model,
            allow_same_family=allow_same,
            timings={"thread_id": thread_id, "ticket_seq": prescreen["ticket_seq"]},
            thread_id=thread_id,
        )
        return _enrich(res)

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
        res = seat_result(
            "ticket",
            repo,
            outcome="unavailable",
            reason=f"void: {parse_error or 'ticket output is not JSON'} (作废)",
            pack=packed,
            configured=configured,
            exam=exam_text,
            task_id=task_id,
            model=model,
            allow_same_family=allow_same,
            thinking=thinking,
            timings={"thread_id": thread_id, "ticket_seq": prescreen["ticket_seq"]},
            thread_id=thread_id,
        )
        return _enrich(res)

    problems, is_lazy = ticket_verdict_problems(verdict, prescreen, portrait, intent_body)
    retried_void = False
    retried_lazy = False
    if problems:
        retried_void = True
        if is_lazy:
            retried_lazy = True
        retry_messages = [
            *messages,
            {"role": "assistant", "content": json.dumps(verdict, ensure_ascii=False)},
            {
                "role": "user",
                "content": (
                    f"VOID / LAZY-REVIEW REJECTED ({'; '.join(problems)}): "
                    "You MUST restate `understood_goal` in your own plain words (never copy-paste ticket text or prior reviews), "
                    "provide all 3 dimension `scores` (`goal_clarity`, `anchor_chain`, `redline_focus`) with detailed ticket-specific "
                    "comments (>=15 chars), cite concrete `portrait:...` evidence on every fail item, and set `verdict`='reject' "
                    "if any dimension has score < 7 or status='fail'. Return the fixed JSON object only."
                ),
            },
        ]
        try:
            retry_content, retry_reasoning = complete_chat(run_cfg, retry_messages)
            thinking = (held["r"] or retry_reasoning or thinking) if spec["live"] else (retry_reasoning or thinking)
            retry_verdict: dict[str, Any] | None = None
            for blob in (retry_content, retry_reasoning):
                if not str(blob or "").strip():
                    continue
                try:
                    retry_verdict = parse_verdict(blob)
                    break
                except ValueError:
                    continue
            if retry_verdict is not None:
                verdict = retry_verdict
                problems, _ = ticket_verdict_problems(verdict, prescreen, portrait, intent_body)
        except RuntimeError:
            pass

    _sync_items_from_scores(verdict)
    items = verdict.get("items") if isinstance(verdict.get("items"), list) else []
    summary = str(verdict.get("summary") or "")
    understood_goal = str(verdict.get("understood_goal") or "").strip()
    doubts = [str(d).strip() for d in (verdict.get("doubts") or []) if str(d).strip()] if isinstance(verdict.get("doubts"), list) else []
    scores = verdict.get("scores") if isinstance(verdict.get("scores"), dict) else {}

    timings_payload: dict[str, Any] = {
        "thread_id": thread_id,
        "ticket_seq": prescreen["ticket_seq"],
        "strict_round_mode": prescreen["strict_round_mode"],
        "understood_goal": understood_goal,
        "summary": summary,
        "scores": scores,
        "doubts": doubts,
        "retried_void": retried_void,
        "retried_lazy": retried_lazy,
    }

    if problems:
        res = seat_result(
            "ticket",
            repo,
            outcome="unavailable",
            reason="void: " + "; ".join(problems),
            pack=packed,
            items=items,
            summary=summary,
            model=model,
            configured=configured,
            exam=exam_text,
            task_id=task_id,
            allow_same_family=allow_same,
            thinking=thinking,
            timings=timings_payload,
            retried_void=retried_void,
            retried_lazy=retried_lazy,
            thread_id=thread_id,
        )
        return _enrich(
            res,
            understood_goal=understood_goal,
            doubts=doubts,
            scores=scores,
            retried_lazy=retried_lazy,
        )

    raw_verdict = str(verdict.get("verdict") or verdict.get("outcome") or "").strip().casefold()
    has_item_fail = any(isinstance(item, dict) and _item_status(item) == "fail" for item in items)
    has_score_fail = any(
        isinstance(scores.get(dim), dict)
        and (
            _item_status(scores[dim]) == "fail"
            or (
                isinstance(scores[dim].get("score"), (int, float))
                and not isinstance(scores[dim].get("score"), bool)
                and float(scores[dim]["score"]) < 7
            )
        )
        for dim in _TICKET_DIMS
    )
    if raw_verdict in {"reject", "rejected", "fail", "failed"} or has_item_fail or has_score_fail:
        outcome = "rejected"
    else:
        outcome = "passed"

    res = seat_result(
        "ticket",
        repo,
        outcome=outcome,
        reason="",
        pack=packed,
        items=items,
        summary=summary,
        model=model,
        configured=configured,
        exam=exam_text,
        task_id=task_id,
        allow_same_family=allow_same,
        thinking=thinking,
        timings=timings_payload,
        retried_void=retried_void,
        retried_lazy=retried_lazy,
        thread_id=thread_id,
    )
    return _enrich(
        res,
        understood_goal=understood_goal,
        doubts=doubts,
        scores=scores,
        retried_lazy=retried_lazy,
    )


def attach_ticket_review(
    enrolled: Path,
    *,
    intent_body: str = "",
    portrait: str = "",
    anchors: list[dict[str, Any]] | None = None,
    redlines: list[str] | None = None,
    task_id: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """Run startup ticket review (0-token script prescreen + stateless DS 3D seat) and return task metadata."""
    try:
        raw = ticket_run(
            enrolled,
            intent_body=intent_body,
            portrait=portrait,
            anchors=anchors,
            redlines=redlines,
            task_id=task_id,
        )
        prescreen_failed = str(raw.get("reason") or "") == "script-prescreen-rejected"
        blob: dict[str, Any] = {
            "outcome": str(raw.get("outcome") or "unavailable"),
            "reason": str(raw.get("reason") or ""),
            "store": str(raw.get("store") or ""),
            "prompt_version": str(raw.get("prompt_version") or "ag.ticket.v1"),
            "configured": bool(raw.get("configured") or prescreen_failed),
            "report_id": str(raw.get("report_id") or ""),
            "thread_id": str(raw.get("thread_id") or ""),
            "understood_goal": str(raw.get("understood_goal") or ""),
            "doubts": list(raw.get("doubts") or []),
            "scores": dict(raw.get("scores") or {}),
            "items": list(raw.get("items") or []),
            "summary": str(raw.get("summary") or ""),
            "script_digest": dict(raw.get("script_digest") or {}),
            "retried_lazy": bool(raw.get("retried_lazy")),
        }
        if raw.get("model"):
            blob["model"] = raw["model"]
        return blob
    except Exception as exc:
        cfg = load_config(enrolled)
        configured = bool(cfg.get("error") or _configured(cfg))
        thread_id = f"tr-{task_id or 'init'}-{uuid.uuid4().hex[:8]}"
        rid = append_log(
            "ticket",
            enrolled,
            outcome="unavailable",
            reason=f"failed: {exc}",
            configured=configured,
            exam=portrait or intent_body,
            task_id=task_id,
            timings={"thread_id": thread_id},
        )
        return {
            "outcome": "unavailable",
            "reason": f"failed: {exc}",
            "store": "",
            "prompt_version": "ag.ticket.v1",
            "configured": configured,
            "report_id": rid,
            "thread_id": thread_id,
            "understood_goal": "",
            "doubts": [],
            "scores": {},
            "items": [],
            "summary": "",
            "script_digest": {},
            "retried_lazy": False,
        }


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
    redlines: list[str] | None = None,
) -> dict[str, Any]:
    if kind == "ticket":
        return ticket_run(
            root,
            portrait=str(exam or ""),
            intent_body=str(exam or ""),
            redlines=redlines,
            task_id=task_id,
        )
    spec = _spec(kind)
    if spec["live"]:
        try:
            path = project_dir(root) / f"{kind}-live.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        except OSError:
            pass
    pack_kwargs: dict[str, Any] = {
        "exam": exam,
        "exam_file": exam_file,
        "base": base,
        "head": head,
        "tree": tree,
    }
    try:
        if "redlines" in inspect.signature(pack).parameters:
            pack_kwargs["redlines"] = redlines
    except (TypeError, ValueError):
        pass
    packed = pack(root, **pack_kwargs)
    if kind == "switch":
        packed = _user_pack(packed, critic)
    packed["redlines"] = [str(item).strip() for item in (redlines or []) if str(item).strip()]
    thread_id = f"{SEATS[kind]['table'][:2]}-{task_id or 'run'}-{uuid.uuid4().hex[:8]}"
    packed["thread_id"] = thread_id
    cfg = load_config(root)
    configured = bool(cfg.get("error") or _configured(cfg))
    extra: dict[str, Any] = {
        "configured": configured,
        "exam": str(packed.get("exam") or ""),
        "task_id": task_id,
        "probe_red": probe_red,
        "thread_id": thread_id,
    }

    def finish(**kwargs: Any) -> dict[str, Any]:
        merged = dict(extra)
        merged.update(kwargs)
        return seat_result(kind, root, pack=packed, **merged)

    script_digest = packed.get("script_digest") if isinstance(packed.get("script_digest"), dict) else {}
    syntax_errors = script_digest.get("syntax_errors") if isinstance(script_digest, dict) else None
    if isinstance(syntax_errors, list) and syntax_errors:
        err_items: list[dict[str, str]] = []
        for err in syntax_errors:
            if isinstance(err, dict):
                ev = str(err.get("evidence") or err.get("locator") or "").strip()
                if not ev and err.get("path"):
                    ev = f"{err.get('path')}:{err.get('line') or 1}"
                msg = str(err.get("comment") or err.get("error") or err.get("message") or ev)
            else:
                msg = str(err).strip()
                m = _EVIDENCE_REF.search(msg)
                ev = m.group(0) if m else f"portrait:{msg[:40]}"
            if not _EVIDENCE_REF.search(ev):
                ev = f"portrait:{ev or 'syntax_error'}"
            err_items.append(
                {
                    "name": "script_syntax_error",
                    "status": "fail",
                    "evidence": ev,
                    "comment": msg,
                }
            )
        return finish(
            outcome="rejected",
            reason="script-syntax-error",
            items=err_items,
            summary="本地脚本语法预检未通过",
            timings={"script_short_circuit": True, "thread_id": thread_id},
        )

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

    def live_log(reasoning_text: str, content_text: str) -> None:
        try:
            path = project_dir(root) / f"{kind}-live.jsonl"
            row = {
                "schema": f"ag.{kind}-live.v1",
                "task_id": task_id,
                "thread_id": thread_id,
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                "reasoning": str(reasoning_text)[-12000:],
                "content": str(content_text)[-12000:],
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()
        except Exception:
            pass

    def on_delta(reasoning_text: str, content_text: str) -> None:
        held["r"] = reasoning_text
        held["c"] = content_text
        live_log(reasoning_text, content_text)

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
    if problems and all("fail without path:line" in p for p in problems):
        retry_messages = [
            *messages,
            {"role": "assistant", "content": json.dumps(verdict, ensure_ascii=False)},
            {
                "role": "user",
                "content": (
                    "VOID FORMAT: Every item with status='fail' MUST include a concrete evidence locator "
                    "matching path:line (e.g. src/foo.py:42), portrait:..., or probe:<id>. "
                    "Fix the evidence fields and return the JSON object only."
                ),
            },
        ]
        try:
            retry_content, retry_reasoning = complete_chat(run_cfg, retry_messages)
            if spec["live"]:
                extra["thinking"] = held["r"] or retry_reasoning or extra.get("thinking", "")
            else:
                extra["thinking"] = retry_reasoning or extra.get("thinking", "")
            retry_verdict: dict[str, Any] | None = None
            for blob in (retry_content, retry_reasoning):
                if not str(blob or "").strip():
                    continue
                try:
                    retry_verdict = parse_verdict(blob)
                    break
                except ValueError:
                    continue
            if retry_verdict is not None:
                verdict = retry_verdict
                problems = verdict_problems(verdict)
                extra["retried_void"] = True
                extra["timings"] = {"retried_void": True, "thread_id": thread_id}
        except RuntimeError:
            pass
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
    redlines: list[str] | None = None,
) -> dict[str, Any] | tuple[dict[str, Any], list[Any]]:
    sealed = [str(item).strip() for item in (redlines or []) if str(item).strip()]
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
                redlines=sealed,
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
            if raw.get("thread_id"):
                blob["thread_id"] = str(raw["thread_id"])
            if raw.get("model"):
                blob["model"] = raw["model"]
            if isinstance(raw.get("items"), list):
                blob["items"] = raw["items"]
            if raw.get("summary"):
                blob["summary"] = str(raw["summary"])
            if kind in {"critic", "switch"} and str(raw.get("outcome") or "") == "rejected":
                from .probe import plant_from_reject

                planted = list(plant_from_reject(enrolled, items=raw.get("items"), tree=worktree) or [])
                blob["probes_planted"] = planted
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
    if kind in {"critic", "switch"}:
        blob["redlines"] = sealed
    if kind == "critic":
        return blob, planted
    return blob
