"""The task intent document lives in the ag home, never in the project.

`<AG_HOME>/projects/<key>/ticket.md` is the one master. `## 意图` stays as written;
start seals red lines into `## 红线` and `redlines.copy`. Start, verify, and finish
rewrite only `## 现场`. The project keeps no copy: delete the ag home and the repo
still builds, commits, and releases.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .managed import ChainBroken, real_root
from .store import project_dir

TICKET_NAME = "ticket.md"
COPY_NAME = "redlines.copy"
TICKETS_DIR_NAME = "tickets"
_HEADING = re.compile(r"^##\s*(意图|红线|现场)\s*$")
_BULLET = re.compile(r"^(?:[-*•]+|\d+[.)])\s+")

STARTER_TICKET_TEMPLATE = """# 票

## 意图
做成之后：请在此用大白话写明本票要解决的业务目标与可观察的完成态（让未看过上下文的新审核线程也能一眼看懂）。

anchor: 在目标模块中建立核心行为闭环：当输入合法参数或触发正常流程时完成预期处理并返回结果，若输入非法或越界则立即拒绝并给出明确错误提示

## 红线
- 聚焦边界铁律：请写明本票严禁触碰的文件、接口或行为底线（必须具体可验证，切勿写“保证代码质量/不要出bug”等空泛套话）。
"""


def home_dir(root: Path) -> Path:
    """Where this project's tickets live: inside the ag home, keyed by project."""
    return project_dir(root)


def ticket_path(root: Path) -> Path:
    return home_dir(root) / TICKET_NAME


def copy_path(root: Path) -> Path:
    return home_dir(root) / COPY_NAME


def tickets_dir(root: Path) -> Path:
    return home_dir(root) / TICKETS_DIR_NAME


def ensure_starter_ticket(root: Path) -> tuple[Path, bool]:
    """Write the starter ticket into the ag home when the project has none."""
    path = ticket_path(root)
    if path.is_file():
        return path, False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(STARTER_TICKET_TEMPLATE, encoding="utf-8")
    return path, True


def active_ticket_path(root: Path) -> Path:
    """Where the live ticket is: the ag home, nowhere else."""
    return ticket_path(root)


def archived_ticket_docs(root: Path) -> list[Path]:
    folder = tickets_dir(root)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.md") if p.is_file())


def previous_redlines(root: Path) -> list[str]:
    path = copy_path(root)
    if not path.is_file():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    lines: list[str] = []
    for item in raw.splitlines():
        line = item.strip()
        if line and line not in lines:
            lines.append(line)
    return lines


def dropped_redlines(previous: list[str], current: list[str]) -> list[str]:
    keep = set(current)
    return [line for line in previous if line not in keep]


def archive_ticket(root: Path, task_id: str, text: str) -> str:
    tid = str(task_id or "").strip()
    if not tid:
        return ""
    folder = tickets_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{tid}.md"
    target.write_text(text, encoding="utf-8")
    return str(target.resolve())


def require_ticket(root: Path) -> str:
    path = active_ticket_path(root)
    if not path.is_file():
        where = ticket_path(root)
        raise ChainBroken(
            f"ag_start needs a ticket; missing {where} "
            "[原因] 本票意图文件不在 ag 家里 "
            f"[下一步] 请在 {where} 填写 ## 意图、正反行为链路 anchor: 与聚焦 ## 红线（或运行 ag_enroll 自动生成模板）后再调用 ag_start；票不进项目目录"
        )
    return path.read_text(encoding="utf-8")


def split_document(text: str) -> tuple[str, str]:
    """Return the intent body and the red-line body.

    The intent body is the exact `## 意图` slice, or the preamble when that
    heading is absent. Later scene writes must put this slice back unchanged.
    """
    sections: dict[str, list[str]] = {"preamble": []}
    current = "preamble"
    seen: set[str] = set()
    for line in str(text or "").splitlines(keepends=True):
        match = _HEADING.match(line.strip())
        if match:
            current = match.group(1)
            seen.add(current)
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, [])
        sections[current].append(line)
    if "意图" in seen:
        intent = "".join(sections.get("意图") or [])
    else:
        intent = "".join(sections.get("preamble") or [])
    redline = "".join(sections.get("红线") or [])
    return intent, redline


def section_lines(body: str) -> list[str]:
    lines: list[str] = []
    for raw in str(body or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = _BULLET.sub("", line).strip()
        if line and line not in lines:
            lines.append(line)
    return lines
# 开票限制：票是"建机器"，不是"跑流程"。一张票的目标应是建好/修好某段具体代码；
# "造一条业务卡带并端到端跑一遍"是运行，不是票的交付物。命中流程类措辞且未声明
# 收窄为"只建设其中某段代码"时，预筛产出一条 warning（只提醒，不硬拦；判票归审票席位）。
FLOW_TARGET_RE = re.compile(r"端到端|全链路|跑通流程|跑通业务|边到边|end[-\s]?to[-\s]?end|\be2e\b", re.IGNORECASE)
NARROWING_RE = re.compile(r"只建|仅建|只补|仅补|只新增|仅新增|只改|仅改|只修|仅修|本票只|本票仅|其中.{0,12}段|那段代码|这段代码")


def flow_target_warnings(intent_body: str) -> list[str]:
    text = str(intent_body or "")
    if not text.strip():
        return []
    if not FLOW_TARGET_RE.search(text):
        return []
    if NARROWING_RE.search(text):
        return []
    return [
        "票面目标疑似把『跑通业务流程』当成交付物；一张票的目标应是建好/修好该流程缺失的那段具体代码，端到端跑通是运行不是票的交付物。请考虑收窄票面为『建设其中某段代码』，把跑通验证放进 .ag-check 自检。"
    ]

def collect_redlines(redline_body: str, anchors: list[dict[str, Any]]) -> list[str]:
    lines = section_lines(redline_body)
    for item in anchors:
        if not isinstance(item, dict) or str(item.get("kind") or "") != "hard":
            continue
        text = str(item.get("text") or "").strip()
        if text and text not in lines:
            lines.append(text)
    return lines


def merge_anchors(
    document_anchors: list[dict[str, Any]],
    caller_anchors: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    merged = [dict(item) for item in document_anchors if isinstance(item, dict)]
    seen = {str(item.get("text") or "").strip() for item in merged}
    for item in caller_anchors or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        row = dict(item)
        row["text"] = text
        if not str(row.get("id") or "").strip():
            row["id"] = f"a{len(merged) + 1}"
        merged.append(row)
    return merged


def scene_text(task: dict[str, Any], *, process: str, product: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [
        f"task: {task.get('id') or ''}",
        f"process: {process}",
        f"product: {product}",
        f"worktree: {task.get('worktree') or ''}",
        f"branch: {task.get('branch') or ''}",
    ]
    if isinstance(task.get("ticket_review"), dict):
        tr = task["ticket_review"]
        outcome = str(tr.get("outcome") or "").strip()
        rid = str(tr.get("report_id") or "").strip()
        tid = str(tr.get("thread_id") or "").strip()
        if outcome:
            rows.append(
                f"ticket_review: {outcome}"
                + (f" ({rid})" if rid else "")
                + (f" [{tid}]" if tid else "")
            )
    rows.append(f"updated: {stamp}")
    return "\n".join(rows) + "\n"


def seal(
    root: Path,
    *,
    intent_body: str,
    redlines: list[str],
    task: dict[str, Any],
    process: str,
    product: str,
) -> str:
    path = ticket_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    intent = intent_body
    if intent and not intent.endswith("\n"):
        intent += "\n"
    red = "".join(f"- {line}\n" for line in redlines)
    scene = scene_text(task, process=process, product=product)
    text = f"# 票\n\n## 意图\n{intent}\n## 红线\n{red}\n## 现场\n{scene}"
    path.write_text(text, encoding="utf-8")
    copy_path(root).write_text(("\n".join(redlines) + "\n") if redlines else "", encoding="utf-8")
    archive_ticket(root, str(task.get("id") or ""), text)
    return text


def write_scene(root: Path, task: dict[str, Any], *, process: str, product: str) -> str | None:
    """Rewrite `## 现场` only. Missing ticket file is left absent."""
    path = ticket_path(root)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    block = "## 现场\n" + scene_text(task, process=process, product=product)
    lines = text.splitlines(keepends=True)
    cut: int | None = None
    for index, line in enumerate(lines):
        match = _HEADING.match(line.strip())
        if match and match.group(1) == "现场":
            cut = index
            break
    if cut is None:
        body = text if text.endswith("\n") else text + "\n"
        if not body.endswith("\n\n"):
            body += "\n"
        updated = body + block
    else:
        updated = "".join(lines[:cut]) + block
    path.write_text(updated, encoding="utf-8")
    if str(task.get("id") or "").strip():
        archive_ticket(root, str(task.get("id") or ""), updated)
    return updated
