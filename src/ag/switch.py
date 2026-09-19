"""Switch seat: the finish gate. Critic is the layer before this."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .managed import ChainBroken, ag_home, project_key, real_root

RUN_SCHEMA = "ag.switch-run.v1"
PROMPT_NAME = "switch_prompt.md"
PROMPT_VERSION = "ag.switch.v1"
REPORT_NAME = "switch-last.json"
LOG_NAME = "switch.jsonl"

TOOLS = [
    {
        "name": "ag_switch_run",
        "description": (
            "One switch chat on the exam pack. Configured deny/void refuse finish. "
            "Not-configured does not. Critic does not refuse finish."
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


def append_log(root: Path, **kwargs: Any) -> str:
    from .seat import append_log as seat_append

    if "pack" not in kwargs and "pack_blob" in kwargs:
        kwargs["pack"] = kwargs.pop("pack_blob")
    kwargs.pop("prompt_version", None)
    return seat_append("switch", root, **kwargs)


def _user_pack(packed: dict[str, Any], critic: dict[str, Any] | None) -> dict[str, Any]:
    from .seat import _user_pack as seat_user_pack

    return seat_user_pack(packed, critic)


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
    from .seat import seat_run

    return seat_run(
        "switch",
        root,
        exam=exam,
        exam_file=exam_file,
        base=base,
        head=head,
        tree=tree,
        task_id=task_id,
        probe_red=probe_red,
        critic=critic,
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
    if not switch or not bool(switch.get("configured")):
        return ""
    outcome = str(switch.get("outcome") or "").strip().casefold()
    if outcome in {"passed", "pass", "allow"}:
        return ""
    reason = str(switch.get("reason") or "").strip()
    if outcome in {"unavailable", ""} and reason == "not-configured":
        return ""
    rid = report_id_from_verify(verify)
    suffix = f"; report_id={rid}" if rid else ""
    if outcome in {"rejected", "reject", "deny", "denied"}:
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
    from .seat import attach_verify as seat_attach

    raw = seat_attach(
        "switch",
        enrolled,
        worktree=worktree,
        portrait=portrait,
        task_id=task_id,
        probe_red=probe_red,
        critic=critic,
        tests_failed=tests_failed,
    )
    return raw if isinstance(raw, dict) else raw[0]


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
