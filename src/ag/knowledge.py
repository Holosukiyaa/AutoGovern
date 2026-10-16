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

from .managed import real_root
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
- 每张票一份 sessions/<task_id>.json，只追加、不改写、不删除历史条目。
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
    anchor_ids = [str(a.get("id") or "") for a in anchors if str(a.get("id") or "").strip()]
    switch_outcome, switch_rid = _seat_outcome(verify, "switch")
    critic_outcome, critic_rid = _seat_outcome(verify, "critic")
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
    base = knowledge_dir(repo)
    readme = base / README_NAME
    if not readme.is_file():
        _atomic_write(readme, _README)
    task_id = record.get("task_id") or "unknown"
    target = base / SESSIONS_NAME / f"{task_id}.json"
    _atomic_write(target, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return str(target)

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


def _iter_sessions(base: Path) -> list[dict[str, Any]]:
    folder = base / SESSIONS_NAME
    if not folder.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(blob, dict):
            out.append(blob)
    return out


def distill(root: Path) -> dict[str, Any]:
    """Distill all sessions/*.json into insights.json. Local rules only, no AI.

    hot_files / stubborn_probes / abandon_rate / reject_focus.
    Index only: counts, task ids, file names, probe ids. Never exam/diff/source/keys.
    """
    repo = real_root(root)
    base = knowledge_dir(repo)
    sessions = _iter_sessions(base)

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

    insights = {
        "schema": "ag.knowledge.insights.v1",
        "generated_at": _utc_now(),
        "session_count": total,
        "hot_files": hot_files,
        "stubborn_probes": stubborn_probes,
        "abandon_rate": abandon_rate,
        "reject_focus": reject_focus,
    }
    _atomic_write(insights_path(repo), json.dumps(insights, ensure_ascii=False, indent=2) + chr(10))
    return insights


def dream(root: Path) -> dict[str, Any]:
    """Manual distill command. Never raises — returns empty structure on any failure."""
    try:
        return distill(root)
    except Exception:
        return _empty_insights()
