"""Cross-session knowledge base. See lane. Append-only, never blocks delivery.

每张票跑完校验后，把这张票的会话档案归档进 <AG_HOME>/projects/<key>/knowledge/。
只存结论与索引，不存考卷正文；项目目录零新增；删掉整个 knowledge/ 主流程照常。
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .managed import ChainBroken, real_root
from .store import project_dir

KNOWLEDGE_NAME = "knowledge"
SESSIONS_NAME = "sessions"
README_NAME = "README.md"

_REQUIRED_FIELDS = (
    "task_id",
    "intent_first_line",
    "anchor_ids",
    "touched_files",
    "check_exit",
    "switch_outcome",
    "switch_report_id",
    "critic_outcome",
    "critic_report_id",
    "probe_red",
    "process",
    "product",
    "archived_at",
)

_README = """# knowledge/ — 跨会话项目总账（Dreaming 第一块砖）

这目录是什么：每张 ag 票跑完校验后，把这张票的会话档案（结论与索引）追加归档到这。
它属于哪个项目：见同级目录 project.txt 里记录的项目根绝对地址。

规则（append-only）：
- 新会话结论追加到项目 history/ 的校验分卷；兼容读取旧 sessions/<task_id>.json。
- 只存结论与索引（outcome / report_id / 红名单 / 文件清单 / exit），不存考卷正文、diff 原文、自检源码、密钥明文。
- 单向指向：知识库指向项目，项目不反向依赖它。

删掉安全：把这整个 knowledge/ 目录删了，项目与 ag 主流程（status/verify/finish/abandon）照常运转。
它只是脚手架式的记忆，不是项目的一部分。
"""


def knowledge_dir(root: Path) -> Path:
    return project_dir(root) / KNOWLEDGE_NAME


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _first_line(text: Any, limit: int = 120) -> str:
    return (str(text or "").strip().splitlines() or [""])[0][:limit]


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp = Path(raw)
    try:
        with open(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        temp.replace(path)
    finally:
        try:
            temp.unlink()
        except OSError:
            pass


def _seat_outcome(verify: dict[str, Any] | None, seat: str) -> tuple[str, str]:
    if not isinstance(verify, dict):
        return "", ""
    blob = verify.get(seat)
    if not isinstance(blob, dict):
        return "", ""
    return str(blob.get("outcome") or ""), str(blob.get("report_id") or "")


def build_session_record(
    task: dict[str, Any],
    *,
    verify: dict[str, Any] | None,
    touched: list[str],
    check_exit: Any,
    process: str,
    product: str,
) -> dict[str, Any]:
    """组装一张票的归档记录。只取结论与索引，缺项记 None 并标 incomplete。"""
    anchors = [a for a in (task.get("anchors") or []) if isinstance(a, dict)]
    if isinstance(verify, dict) and verify.get("task_id", task.get("id")) != task.get("id"):
        verify = None
    anchor_ids = [str(a.get("id") or "") for a in anchors if str(a.get("id") or "").strip()]
    switch_outcome, switch_rid = _seat_outcome(verify, "switch")
    critic_outcome, critic_rid = _seat_outcome(verify, "critic")
    merged = bool(switch_rid and critic_rid == switch_rid)
    if merged:
        critic_outcome, critic_rid = "", ""
    probe_red = []
    if isinstance(verify, dict):
        probe_red = [str(x) for x in (verify.get("probe_red") or []) if str(x or "").strip()]
    record: dict[str, Any] = {
        "schema": "ag.knowledge.session.v1",
        "task_id": str(task.get("id") or ""),
        "intent_first_line": _first_line(task.get("portrait")),
        "anchor_ids": anchor_ids,
        "touched_files": [str(t) for t in (touched or [])],
        "check_exit": check_exit if check_exit is not None else None,
        "switch_outcome": switch_outcome or None,
        "switch_report_id": switch_rid or None,
        "critic_outcome": critic_outcome or None,
        "critic_report_id": critic_rid or None,
        "critic_merged_into": "switch" if merged else None,
        "candidate": (verify or {}).get("candidate") or None,
        "check_argv": (verify or {}).get("check_argv") or [],
        "probe_red": probe_red,
        "process": str(process or ""),
        "product": str(product or ""),
        "archived_at": _utc_now(),
    }
    # 必备结论缺一项即 incomplete：票号、switch 结论、自检 exit、锚点。缺的不报错不拦，只标记。
    missing_core = any(record.get(field) in (None, "", []) for field in ("task_id", "switch_outcome"))
    if not anchor_ids or check_exit is None:
        missing_core = True
    record["incomplete"] = bool(missing_core)
    return record


# --- review (复盘) ------------------------------------------------------------

_REDLINES_NAME = "redlines.md"


def redlines_path(root: Path) -> Path:
    return knowledge_dir(real_root(root)) / _REDLINES_NAME


def _intent_excerpt(task: dict[str, Any]) -> str:
    """Extract the ticket's plain-language intent, never raw exam prose.

    Privacy rule: the sealed exam body (portrait / intent / anchor_preview full text)
    must NOT land verbatim into sessions/*.json. We only keep a short cleaned clause.

    Priority: portrait first line, then intent first line, then the first plain
    sentence under the `## 意图` heading of anchor_preview (skipping anchor:/#/list lines,
    stripping filler prefixes like '大白话：').
    """
    for key in ("portrait", "intent"):
        first = str(task.get(key) or "").strip().splitlines()
        if first and first[0].strip():
            return first[0].strip()
    text = str(task.get("anchor_preview") or "")
    if not text.strip():
        return ""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("## ") and "意图" in ln:
            start = i + 1
            break
    if start is None:
        return ""
    for ln in lines[start:]:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("## "):
            return ""
        if s.startswith("anchor:") or s.startswith("#"):
            continue
        s = s.lstrip("-*>").strip()
        for prefix in ("大白话：", "大白话:", "固定：", "固定:"):
            if s.startswith(prefix):
                s = s[len(prefix):].strip()
                break
        if s:
            return s
    return ""


def _theme_label(task: dict[str, Any]) -> str:
    """A short topic label for the ticket, not the exam body.

    Prefers the intent's first short clause; strips code/quotes/long tokens so what
    lands in the review is a label like '修复孤岛误报', not the ticket's prose.
    Falls back to the `## 意图` paragraph in anchor_preview when portrait/intent are empty."""
    # 隐私铁律：考卷正文不直接落盘。_intent_excerpt 已按 portrait>intent>anchor_preview
    # 优先序取出人话意图句，再经 _sanitize 清洗后才作为主题。
    s = _sanitize(_intent_excerpt(task))
    # keep only the first clause, drop colons/anchors so it reads as a label
    for sep in ("，", "。", "：", ":", ";", "；", "——", "——"):
        if sep in s:
            s = s.split(sep)[0]
    return s.strip()[:40]


def _sanitize(text: str) -> str:
    """Strip code/diff/secret-like fragments from a review comment, keep the conclusion.

    Removes inline code spans, long tokens, file:line refs, and JSON blobs so the
    retrospective stores the lesson, not the exam body."""
    import re as _re

    s = str(text or "")
    s = _re.sub(r"`[^`]*`", "", s)                       # inline code spans
    s = _re.sub(r"\{[^{}]*\}", "", s)                   # JSON-ish blobs
    s = _re.sub(r"[\w./\\-]+\.(py|json|md|jsonl|ts|js):\d+", "[file]", s)  # file:line refs
    s = _re.sub(r"[A-Za-z0-9+/=_-]{32,}", "[token]", s)  # long tokens / hashes / keys
    s = _re.sub(r"\s+", " ", s).strip()
    return s


def build_review(root: Path, task: dict[str, Any], verify: dict[str, Any] | None, *, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Distill a ticket's retrospective: what it tried, what it found, what went right/wrong.

    Conclusions and indexes only — never exam text, diff source, or secrets."""
    from .delivery import task_reviews

    task_id = str(task.get("id") or "")
    events = task_reviews(root, task_id) if events is None else events
    events = [row for row in events if row.get("task_id") == task_id and row["seat"] in {"switch", "critic"}]
    items = [item for row in events for item in row.get("items") or [] if isinstance(item, dict)]

    went_well = [str(i.get("name") or "") for i in items if str(i.get("status") or "").casefold() == "pass" and str(i.get("name") or "").strip()]
    wrong_items = [i for i in items if str(i.get("status") or "").casefold() == "fail"]
    went_wrong = [str(i.get("name") or "") for i in wrong_items if str(i.get("name") or "").strip()]
    found = []
    for i in wrong_items:
        comment = _sanitize(str(i.get("comment") or ""))
        if comment:
            found.append(f"{i.get('name') or '?'}: {comment[:160]}")

    rejected = [row for row in events if row.get("outcome") == "rejected"]
    passed = [row for row in events if row.get("outcome") == "passed"]
    if not events:
        lesson = "本票未完成终审，不能判定一次通过或修复成功。"
    elif rejected:
        lesson = f"本票记录 {len(rejected)} 次拒绝、{len(passed)} 次通过；是否误报或真实修复须另有行为证据。"
    elif passed:
        lesson = "本票终审通过，未记录拒绝；结论只来自本票原始事件。"
    else:
        lesson = "本票有审核尝试但尚无通过结论。"

    return {
        "problem_wanted": _theme_label(task),
        "problem_found": found,
        "went_well": went_well,
        "went_wrong": went_wrong,
        "lesson": lesson,
        "reports": [{"report_id": row["report_id"], "outcome": row.get("outcome"), "candidate": row.get("candidate"), "source": row["ref"]} for row in events],
        "rejections": len(rejected),
        "passes": len(passed),
    }


def append_redlines(root: Path, task: dict[str, Any]) -> int:
    """Append this ticket's redlines to the cumulative project redlines.md. Append-only.

    Returns the number of redline entries appended. Never deletes history."""
    repo = real_root(root)
    standing = set(load_standing_redlines(repo))
    lines = [
        str(rule)
        for rule in (task.get("redlines") or [])
        if str(rule or "").strip() and str(rule).strip() not in standing
    ]
    if not lines:
        return 0
    path = redlines_path(repo)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if not existing:
        existing = "# 项目红线册（跨票累积，append-only）\n\n每次 finish 把本票红线追加到这。过期标 [obsolete]，不删历史。\n"
    topic = _theme_label(task) or "(无主题)"
    tid = str(task.get("id") or "")
    stamp = _utc_now()[:10]
    block = f"\n## {stamp} · {tid} · {topic}\n" + "\n".join(f"- {line}" for line in lines) + "\n"
    _atomic_write(path, existing.rstrip("\n") + "\n" + block)
    return len(lines)


def load_active_redlines(root: Path) -> list[str]:
    """All non-obsolete redlines from the cumulative book, fed to the next ticket's review."""
    path = redlines_path(real_root(root))
    if not path.is_file():
        return []
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("- ") and "[obsolete]" not in s:
            out.append(s[2:].strip())
    return [x for x in out if x]


def load_standing_redlines(root: Path) -> list[str]:
    """Read explicitly standing rules; unreadable existing sources must not disappear."""
    path = redlines_path(real_root(root))
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeError) as exc:
        raise ChainBroken(f"standing-redlines-unreadable: {path}: {exc}") from exc
    rules: list[str] = []
    inside = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            inside = stripped[3:].strip().startswith("常设红线")
            continue
        if inside and stripped.startswith("- "):
            rule = stripped[2:].strip()
            if rule and "[obsolete]" not in rule and rule not in rules:
                rules.append(rule)
    return rules


def archive_session(
    root: Path,
    task: dict[str, Any],
    *,
    verify: dict[str, Any] | None = None,
    touched: list[str] | None = None,
    check_exit: Any = None,
    process: str = "",
    product: str = "",
) -> str:
    """把一张票归档进知识库。append-only；任何失败都抛给调用方去吞，绝不拦截交付。"""
    repo = real_root(root)
    record = build_session_record(
        task,
        verify=verify,
        touched=list(touched or []),
        check_exit=check_exit,
        process=process,
        product=product,
    )
    record["review"] = build_review(repo, task, verify)
    base = knowledge_dir(repo)
    readme = base / README_NAME
    if not readme.is_file():
        _atomic_write(readme, _README)
    from .delivery import task_reviews
    from .history import append_fact

    task_id = record.get("task_id") or "unknown"
    events = task_reviews(repo, task_id)
    for seat in ("switch", "critic"):
        report_id = record.get(seat + "_report_id")
        if report_id and not any(row["report_id"] == report_id and row.get("task_id") == task_id for row in events):
            record[seat + "_report_id"] = None
            record[seat + "_outcome"] = None
            record["incomplete"] = True
    return append_fact(repo, "session", task_id, record)

INSIGHTS_NAME = "insights.json"


def insights_path(root: Path) -> Path:
    return knowledge_dir(root) / INSIGHTS_NAME


def _empty_insights() -> dict[str, Any]:
    return {
        "schema": "ag.knowledge.insights.v1",
        "generated_at": "",
        "session_count": 0,
        "hot_files": [],
        "stubborn_probes": [],
        "abandon_rate": {"total": 0, "abandoned": 0, "ratio": 0.0, "high": False},
        "reject_focus": [],
    }


def load_insights(root: Path) -> dict[str, Any]:
    """Read the current insights snapshot; missing or corrupt returns empty, never raises."""
    path = insights_path(real_root(root))
    if not path.is_file():
        return _empty_insights()
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_insights()
    return blob if isinstance(blob, dict) else _empty_insights()


def _iter_sessions(base: Path, root: Path | None = None) -> list[dict[str, Any]]:
    folder = base / SESSIONS_NAME
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(blob, dict):
            out.append(blob)
    if root is not None:
        from .history import read_records

        out.extend(row["payload"] for row in read_records(root, kind="session"))
    unique = {}
    for row in sorted(out, key=lambda row: str(row.get("archived_at") or "")):
        unique[str(row.get("task_id") or "")] = row
    sessions = list(unique.values())
    if root is not None:
        from .delivery import task_reviews

        for index, stored in enumerate(sessions):
            session = dict(stored)
            task_id = str(session.get("task_id") or "")
            events = task_reviews(root, task_id)
            reports = {row["report_id"]: row for row in events}
            diagnostics = []
            for seat in ("switch", "critic"):
                report_id = session.get(seat + "_report_id")
                original = reports.get(str(report_id or ""))
                if original and original["seat"] in {"switch", "critic"} and (not session.get("candidate") or original.get("candidate") == session["candidate"]):
                    session[seat + "_outcome"] = original.get("outcome")
                else:
                    if report_id:
                        diagnostics.append({"kind": "unbound-review", "report_id": report_id, "task_id": task_id})
                    session[seat + "_report_id"] = None
                    session[seat + "_outcome"] = None
            if session.get("critic_report_id") and session["critic_report_id"] == session.get("switch_report_id"):
                session["critic_report_id"] = None
                session["critic_outcome"] = None
                session["critic_merged_into"] = "switch"
            stored_review = session.get("review") if isinstance(session.get("review"), dict) else {}
            session["review"] = build_review(root, {"id": task_id, "portrait": session.get("intent_first_line") or stored_review.get("problem_wanted")}, None, events=events)
            session["review_diagnostics"] = diagnostics
            sessions[index] = session
    return sessions


def distill(root: Path) -> dict[str, Any]:
    """Distill all sessions/*.json into insights.json. Local rules only, no AI.

    hot_files / stubborn_probes / abandon_rate / reject_focus.
    Index only: counts, task ids, file names, probe ids. Never exam/diff/source/keys.
    """
    repo = real_root(root)
    base = knowledge_dir(repo)
    sessions = _iter_sessions(base, repo)

    file_tickets: dict[str, list[dict[str, Any]]] = {}
    for rec in sessions:
        for f in (rec.get("touched_files") or []):
            file_tickets.setdefault(str(f), []).append(rec)
    hot_files = []
    for fname, recs in sorted(file_tickets.items()):
        if len(recs) < 2:
            continue
        if all(str(r.get("switch_outcome") or "") == "rejected" for r in recs):
            hot_files.append({
                "file": fname,
                "count": len(recs),
                "task_ids": sorted({str(r.get("task_id") or "") for r in recs if str(r.get("task_id") or "")}),
            })

    probe_hits: dict[str, set] = {}
    for rec in sessions:
        tid = str(rec.get("task_id") or "")
        for pid in (rec.get("probe_red") or []):
            probe_hits.setdefault(str(pid), set()).add(tid)
    stubborn_probes = [
        {"probe_id": pid, "count": len(tids), "task_ids": sorted(tids)}
        for pid, tids in sorted(probe_hits.items())
        if len(tids) >= 2
    ]

    total = len(sessions)
    abandoned = sum(1 for r in sessions if str(r.get("process") or "") == "abandoned")
    ratio = round(abandoned / total, 3) if total else 0.0
    abandon_rate = {"total": total, "abandoned": abandoned, "ratio": ratio, "high": bool(ratio > 0.5)}

    focus: dict[str, dict[str, Any]] = {}
    for rec in sessions:
        for seat in ("switch", "critic"):
            if seat == "critic" and rec.get("critic_report_id") == rec.get("switch_report_id"):
                continue
            if str(rec.get(seat + "_outcome") or "") == "rejected":
                for f in (rec.get("touched_files") or []):
                    k = seat + ":" + str(f)
                    slot = focus.setdefault(k, {"seat": seat, "file": str(f), "count": 0, "task_ids": set()})
                    slot["count"] += 1
                    if str(rec.get("task_id") or ""):
                        slot["task_ids"].add(str(rec.get("task_id")))
    reject_focus = [
        {"seat": v["seat"], "file": v["file"], "count": v["count"], "task_ids": sorted(v["task_ids"])}
        for v in sorted(focus.values(), key=lambda x: -x["count"])
    ]

    # retrospective patterns across sessions (modes, not a ledger)
    reviewed = [r for r in sessions if isinstance(r.get("review"), dict)]
    gate_passes = sum(1 for r in reviewed if "人工闸门" in str(r["review"].get("lesson") or ""))
    real_defects = sum(1 for r in reviewed if "真缺陷" in str(r["review"].get("lesson") or ""))
    clean_passes = sum(1 for r in reviewed if int(r["review"].get("passes") or 0) > 0 and int(r["review"].get("rejections") or 0) == 0)
    theme_hits: dict[str, int] = {}
    for r in reviewed:
        for name in (r["review"].get("went_wrong") or []):
            theme_hits[str(name)] = theme_hits.get(str(name), 0) + 1
    recurring = sorted([{"theme": k, "count": v} for k, v in theme_hits.items() if v >= 2], key=lambda x: -x["count"])
    review_patterns = {
        "reviewed_tickets": len(reviewed),
        "review_coverage": round(len(reviewed) / total, 3) if total else 0.0,
        "gate_passes": gate_passes,
        "real_defects_fixed": real_defects,
        "clean_passes": clean_passes,
        "recurring_defect_themes": recurring,
    }

    insights = {
        "schema": "ag.knowledge.insights.v1",
        "generated_at": _utc_now(),
        "session_count": total,
        "hot_files": hot_files,
        "stubborn_probes": stubborn_probes,
        "abandon_rate": abandon_rate,
        "reject_focus": reject_focus,
        "review_patterns": review_patterns,
    }
    _atomic_write(insights_path(repo), json.dumps(insights, ensure_ascii=False, indent=2) + chr(10))
    return insights


def dream(root: Path) -> dict[str, Any]:
    """Manual distill command. Source failures remain explicit in the returned view."""
    try:
        return distill(root)
    except (OSError, ValueError, TypeError, ChainBroken) as exc:
        return {**_empty_insights(), "incomplete": True, "error": str(exc), "next_action": "repair-history-source"}


def retro(root: Path, limit: int = 8) -> dict[str, Any]:
    """Human-readable retrospective of recent tickets: what each tried/found/did right/wrong."""
    repo = real_root(root)
    sessions = _iter_sessions(knowledge_dir(repo), repo)
    recent = sessions[-limit:][::-1]
    rows = []
    for rec in recent:
        rev = rec.get("review") if isinstance(rec.get("review"), dict) else {}
        rows.append({
            "task_id": str(rec.get("task_id") or ""),
            "archived_at": str(rec.get("archived_at") or ""),
            "problem_wanted": str(rev.get("problem_wanted") or ""),
            "problem_found": list(rev.get("problem_found") or []),
            "went_well": list(rev.get("went_well") or []),
            "went_wrong": list(rev.get("went_wrong") or []),
            "lesson": str(rev.get("lesson") or ""),
            "reports": list(rev.get("reports") or []),
            "rejections": int(rev.get("rejections") or 0),
            "passes": int(rev.get("passes") or 0),
            "diagnostics": list(rec.get("review_diagnostics") or []),
        })
    return {
        "schema": "ag.knowledge.retro.v1",
        "root": str(repo),
        "session_count": len(sessions),
        "shown": len(rows),
        "tickets": rows,
        "redlines_active": len(load_active_redlines(repo)),
    }
