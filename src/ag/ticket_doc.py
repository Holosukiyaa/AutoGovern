"""The task intent document lives in the ag home, never in the project.

`<AG_HOME>/projects/<key>/ticket.md` is the one master. `## 意图` stays as written;
start seals red lines into `## 红线` and `redlines.copy`. Start, verify, and finish
rewrite only `## 现场`. The project keeps no copy: delete the ag home and the repo
still builds, commits, and releases.
"""
from __future__ import annotations

import hashlib
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .managed import ChainBroken, real_root
from .store import foreign_dir, project_dir

TICKET_NAME = "ticket.md"
COPY_NAME = "redlines.copy"
TICKETS_DIR_NAME = "tickets"
MIGRATION_NAME = "migration.md"
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


def legacy_ticket_path(root: Path) -> Path:
    return foreign_dir(root) / TICKET_NAME


def legacy_copy_path(root: Path) -> Path:
    return foreign_dir(root) / COPY_NAME


def legacy_tickets_dir(root: Path) -> Path:
    return foreign_dir(root) / TICKETS_DIR_NAME


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _note_migration(root: Path, lines: list[str]) -> str:
    if not lines:
        return ""
    path = home_dir(root) / MIGRATION_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "" if path.is_file() else "# 票搬家记录\n\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(header + "".join(f"- {line}\n" for line in lines))
    return str(path)


def migrate_legacy(root: Path) -> dict[str, Any]:
    """One-time move of the three legacy items. Copy, verify sha256, then unlink.

    Only these three are touched: the ticket, the sealed red line copy, and the
    archived tickets folder. Anything else under that directory belongs to the
    project and is left alone; the directory itself is removed only if empty.
    """
    old_dir = foreign_dir(root)
    out: dict[str, Any] = {
        "touched": False,
        "moved": [],
        "skipped": [],
        "conflicts": [],
        "dir_removed": False,
        "record": "",
    }
    if not old_dir.is_dir():
        return out
    out["touched"] = True
    home_dir(root).mkdir(parents=True, exist_ok=True)
    for old, new in (
        (legacy_ticket_path(root), ticket_path(root)),
        (legacy_copy_path(root), copy_path(root)),
    ):
        if not old.is_file():
            continue
        if new.is_file() and _sha256(old) == _sha256(new):
            out["skipped"].append(f"{old.name} 新家已有同样内容，原件保留不动")
            continue
        if new.is_file():
            out["conflicts"].append(
                f"{old.name} 新旧都有且内容不同：以新家为准，原件仍在 {old}"
            )
            continue
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old, new)
        if _sha256(old) != _sha256(new):
            if new.exists():
                new.unlink()
            out["skipped"].append(f"{old.name} 校验不一致，原件未动")
            continue
        old.unlink()
        out["moved"].append(f"{old.name}")
    legacy_tickets = legacy_tickets_dir(root)
    if legacy_tickets.is_dir():
        target = tickets_dir(root)
        target.mkdir(parents=True, exist_ok=True)
        for item in sorted(legacy_tickets.glob("*.md")):
            if not item.is_file():
                continue
            dest = target / item.name
            if dest.is_file():
                if _sha256(item) == _sha256(dest):
                    item.unlink()
                    out["skipped"].append(f"{item.name} 新家已有同样内容，原件已清")
                else:
                    out["conflicts"].append(f"{item.name} 新旧内容不同：以新家为准，原件仍在 {item}")
                continue
            shutil.copy2(item, dest)
            if _sha256(item) != _sha256(dest):
                if dest.exists():
                    dest.unlink()
                out["skipped"].append(f"{item.name} 校验不一致，原件未动")
                continue
            item.unlink()
            out["moved"].append(item.name)
        try:
            legacy_tickets.rmdir()
        except OSError:
            # 目录里还剩不属于 ag 的东西：原样留着，绝不递归删。
            pass
    try:
        old_dir.rmdir()
        out["dir_removed"] = True
    except OSError:
        # 目录非空就不动它：只碰那三样，别人的内容一概不删。
        pass
    lines = [
        f"{_stamp()} 搬家：从 {old_dir} 搬走 {len(out['moved'])} 份"
        + (f"（{', '.join(out['moved'][:6])}{'...' if len(out['moved']) > 6 else ''}）" if out["moved"] else ""),
    ]
    if out["skipped"]:
        lines.append("跳过：" + "；".join(out["skipped"]))
    if out["conflicts"]:
        lines.append("冲突：" + "；".join(out["conflicts"]))
    lines.append(f"遗留目录是否已清空：{'是' if out['dir_removed'] else '否（还有不属于 ag 的内容，原样保留）'}")
    out["record"] = _note_migration(root, lines)
    return out


def active_ticket_path(root: Path) -> Path:
    """Where the live ticket is: the new home wins, else the legacy spot, else the new home."""
    new = ticket_path(root)
    if new.is_file():
        return new
    old = legacy_ticket_path(root)
    if old.is_file():
        return old
    return new


def archived_ticket_docs(root: Path) -> list[Path]:
    out = []
    for folder in (legacy_tickets_dir(root), tickets_dir(root)):
        if folder.is_dir():
            out.extend(sorted(p for p in folder.glob("*.md") if p.is_file()))
    return out


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
    migrate_legacy(root)
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
