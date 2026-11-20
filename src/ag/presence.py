"""Human presence gate and task-bound authorization proofs. No persisted secrets."""
from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .managed import ChainBroken, ag_home
from .store import load_task_timeline
from .ticket_package import sealed_dir

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def temporary_home() -> bool:
    """Resolve symlinks; synthetic authority is meaningful only inside this process's temp."""
    home = ag_home().resolve()
    temporary = Path(tempfile.gettempdir()).resolve()
    return home != (Path.home() / ".ag").resolve() and home != temporary and home.is_relative_to(temporary)


def stdin_console() -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        try:
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetStdHandle.argtypes = [wintypes.DWORD]
            kernel.GetStdHandle.restype = wintypes.HANDLE
            kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel.GetConsoleMode.restype = wintypes.BOOL
            mode = wintypes.DWORD()
            return bool(kernel.GetConsoleMode(kernel.GetStdHandle(-10), ctypes.byref(mode)))
        except (OSError, ValueError):
            return False
    import termios

    try:
        if not os.isatty(0):
            return False
        termios.tcgetattr(0)
        return True
    except (OSError, ValueError, termios.error):
        return False


def check_code(code: str, read_line: Callable[[], str] | None = None) -> None:
    """Only the comparison loop; tests need neither a console nor injected keyboard input."""
    reader = read_line if read_line is not None else sys.stdin.readline
    for attempt in range(1, 4):
        print(f"请输入短码（{attempt}/3）：", end="", file=sys.stderr, flush=True)
        try:
            typed = reader()
        except (EOFError, OSError):
            typed = ""
        if typed.strip().upper() == code:
            return
    raise ChainBroken("human-code-mismatch: three incorrect attempts; approval was not recorded")


def require_human(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    """Call only after existing state checks and before any approval mutation."""
    synthetic = os.environ.get("AG_SYNTHETIC_CONFIRM") == "1" and temporary_home()
    if not synthetic and not stdin_console():
        raise ChainBroken("human-console-required: 请在你自己的 PowerShell 或 cmd 窗口执行；AI 不能代为执行。Git Bash 可尝试 winpty 前缀。")
    folder = sealed_dir(root, task["id"])
    text = (folder / "ticket.md").read_text(encoding="utf-8")
    spec = json.loads((folder / "spec.json").read_text(encoding="utf-8"))
    print(text, end="" if text.endswith("\n") else "\n", file=sys.stderr)
    scope, checks, review = spec["scope"], spec["checks"], task.get("ticket_review") or {}
    targets = sum(row["kind"] == "target" for row in checks)
    guards = sum(row["kind"] == "guard" for row in checks)
    print(f"机器部分：可改 {len(scope['allow'])} 处，禁改 {len(scope.get('deny', []))} 处；自审 {len(checks)} 条（目标 {targets}、守护 {guards}，开票基线已核对）；审票 {review.get('outcome', '')} ({review.get('report_id', '')})", file=sys.stderr, flush=True)
    if synthetic:
        print("合成确认（仅供临时测试）", file=sys.stderr, flush=True)
    else:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
        print(f"请照着输入这 4 个字符：{code}", file=sys.stderr, flush=True)
        check_code(code)
    return {"method": "synthetic" if synthetic else "console", "platform": sys.platform,
            "stdin_console": not synthetic, "at": datetime.now(timezone.utc).isoformat()}


def valid_proof(proof: Any) -> bool:
    return isinstance(proof, dict) and (proof.get("method") == "console" or (proof.get("method") == "synthetic" and temporary_home()))


def _proven_event(root: Path, task: dict[str, Any], phase: str, report_id: str | None = None) -> bool:
    identity = task.get("authorization_identity")
    if not identity:
        return False
    return any(step.get("phase") == phase and step.get("intent_identity") == identity
               and (report_id is None or step.get("report_id") == report_id)
               and valid_proof(step.get("proof"))
               for step in load_task_timeline(root, task["id"])["steps"])


def authorized(root: Path, task: dict[str, Any]) -> bool:
    return task.get("intent_map_confirmed") is True and _proven_event(root, task, "intent-map-confirmed")


def require_authorization(root: Path, task: dict[str, Any]) -> None:
    if not authorized(root, task):
        raise ChainBroken("authorization-unproven: no matching confirmation event with a valid human presence proof")


def require_self_approval(root: Path, task: dict[str, Any], report_id: str) -> None:
    approval = task.get("self_approved")
    if not isinstance(approval, dict) or approval.get("task_id") != task["id"] or approval.get("report_id") != report_id or not _proven_event(root, task, "self-governance-approved", report_id):
        raise ChainBroken("authorization-unproven: no matching self-governance approval event with a valid human presence proof")
