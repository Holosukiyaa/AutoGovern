"""Layout-versioned upgrade chain for project state dirs. Ship lane.

Old projects (<AG_HOME>/projects/<key>) carry no version stamp; new ag stamps
LAYOUT_VERSION. ensure_upgraded() walks a migration table from the stored version
up to the current one, leaving one migration.jsonl line per step. Idempotent,
never raises, never blocks delivery.

The config-fold in settings._migrate() runs first (config兜底); this chain runs
after it and handles what config-fold cannot: stamping, adapter re-slotting by
real language, scaffolding the v0.4 knowledge/ home, and hinting at bloat files.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .managed import real_root
from .store import append_project_jsonl, project_dir

LAYOUT_VERSION = 2
_LAYOUT_FILE = "layout_version"

# Loose flow files from the pre-v0.4 layout. Detected for a prune hint only;
# never deleted by this chain (deletion stays with the user via `ag prune`).
_FLOW_FILES = (
    "critic.jsonl",
    "switch.jsonl",
    "ticket.jsonl",
    "usage.jsonl",
    "critic-live.jsonl",
    "switch-live.jsonl",
    "ticket-live.jsonl",
)

_KNOWLEDGE_README = """# knowledge/ — 跨会话项目总账

每张票跑完校验后，把这张票的会话档案归档进本目录。
只存结论与索引，不存考卷正文；删掉整个 knowledge/ 主流程照常。
"""


def _layout_file(root: Path) -> Path:
    return project_dir(real_root(root)) / _LAYOUT_FILE


def layout_version(root: Path) -> int:
    """Read the stamped layout version. No stamp means a legacy v1 project.
    Corrupt or unreadable stamps also read as 1 so the chain can re-converge."""
    try:
        raw = _layout_file(root).read_text(encoding="utf-8").strip()
        ver = int(raw)
        return ver if ver >= 1 else 1
    except (OSError, ValueError):
        return 1


def _stamp(root: Path, ver: int) -> None:
    _layout_file(root).write_text(str(ver) + chr(10), encoding="utf-8")


def _audit(root: Path, action: str, detail: str) -> None:
    try:
        append_project_jsonl(real_root(root), "migration.jsonl", {"action": action, "detail": detail})
    except Exception:
        import sys
        sys.stderr.write("ag: upgrade migration audit write failed; not logged" + chr(10))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return blob if isinstance(blob, dict) else {}


def _write_json(path: Path, blob: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")


def _match_language(source_exts: Any) -> str:
    """Pick the built-in language whose ext set best overlaps the given exts."""
    from .settings import default_adapters

    exts = {str(e).lower() for e in (source_exts or [])}
    if not exts:
        return ""
    best, best_overlap = "", 0
    for lang, cfg in default_adapters().items():
        overlap = len(exts & {str(e).lower() for e in (cfg.get("source_exts") or [])})
        if overlap > best_overlap:
            best, best_overlap = lang, overlap
    return best


def _step_reslot_adapters(root: Path) -> str:
    """Move an adapter that sits in the wrong language slot to its real language.
    Legacy folds dropped every old adapter into the python slot; re-slot by exts."""
    from .settings import default_adapters, settings_path

    path = settings_path(root)
    blob = _read_json(path)
    struct = blob.get("structure")
    if not isinstance(struct, dict):
        return "no structure section"
    adapters = struct.get("adapters")
    if not isinstance(adapters, dict):
        return "no adapters table"
    builtin = default_adapters()
    moved: list[str] = []
    for slot, cfg in list(adapters.items()):
        if not isinstance(cfg, dict):
            continue
        real = _match_language(cfg.get("source_exts"))
        if not real or real == slot:
            continue
        # wrong slot: move to the real language slot, restore builtin at the old slot
        adapters[real] = cfg
        if slot in builtin:
            adapters[slot] = dict(builtin[slot])
        else:
            adapters.pop(slot, None)
        moved.append(f"{slot}->{real}")
    if moved:
        _write_json(path, blob)
    return "reslot " + ",".join(moved) if moved else "no mislotted adapter"


def _step_scaffold_home(root: Path) -> str:
    """Build the v0.4 home for a legacy project: knowledge/ dir + README, and
    top up config.json to the full v2 sections. Fills only what's missing."""
    from .knowledge import knowledge_dir
    from .settings import (
        _CRITIC_DEFAULTS,
        _PRUNE_DEFAULTS,
        default_adapters,
        settings_path,
    )

    base = project_dir(real_root(root))
    made: list[str] = []
    kdir = knowledge_dir(real_root(root))
    if not kdir.is_dir():
        kdir.mkdir(parents=True, exist_ok=True)
        made.append("knowledge/")
    readme = kdir / "README.md"
    if not readme.is_file():
        readme.write_text(_KNOWLEDGE_README, encoding="utf-8")
        made.append("knowledge/README.md")

    path = settings_path(root)
    blob = _read_json(path)
    filled: list[str] = []
    if not isinstance(blob.get("critic"), dict):
        blob["critic"] = dict(_CRITIC_DEFAULTS)
        filled.append("critic")
    struct = blob.get("structure")
    if not isinstance(struct, dict) or not isinstance(struct.get("adapters"), dict):
        blob["structure"] = {"enabled": True, "adapters": default_adapters()}
        filled.append("structure")
    if not isinstance(blob.get("prune"), dict):
        blob["prune"] = dict(_PRUNE_DEFAULTS)
        filled.append("prune")
    if not isinstance(blob.get("plugins"), dict) or "lanes" not in blob.get("plugins", {}):
        from .settings import _catalog_listing

        off = []
        blob["plugins"] = {"off": off, "lanes": _catalog_listing(off)}
        filled.append("plugins")
    if filled:
        blob["schema"] = "ag.config.v2"
        _write_json(path, blob)
    if made or filled:
        return "scaffold " + ",".join(made + filled)
    return "home already complete"


def _step_flow_hint(root: Path) -> str:
    """Detect loose legacy flow files and leave a prune hint. Never deletes."""
    base = project_dir(real_root(root))
    total = 0
    found: list[str] = []
    for name in _FLOW_FILES:
        f = base / name
        try:
            if f.is_file():
                found.append(name)
                total += f.stat().st_size
        except OSError:
            pass
    if not found:
        return "no loose flow files"
    mb = total / (1024 * 1024)
    return f"detected {len(found)} flow files {mb:.1f}MB; run `ag prune` to clean (not auto-deleted)"


# (from_version, to_version, step). Walked in order from the stored version.
MIGRATIONS: list[tuple[int, int, Callable[[Path], str]]] = [
    (1, 2, _step_reslot_adapters),
    (1, 2, _step_scaffold_home),
    (1, 2, _step_flow_hint),
]


def ensure_upgraded(root: Path) -> dict[str, Any]:
    """Walk the migration chain up to LAYOUT_VERSION. Idempotent, never raises."""
    root = real_root(root)
    out: dict[str, Any] = {"from": None, "to": None, "ran": [], "upgraded": False}
    try:
        cur = layout_version(root)
        out["from"] = cur
        out["to"] = cur
        if cur >= LAYOUT_VERSION:
            return out
        ran: list[str] = []
        failed = 0
        for frm, to, step in MIGRATIONS:
            if cur < to:
                try:
                    detail = step(root)
                    ran.append(f"{frm}->{to}:{step.__name__}")
                    _audit(root, f"upgrade-{frm}-to-{to}", f"{step.__name__}: {detail}")
                except Exception as exc:
                    failed += 1
                    _audit(root, f"upgrade-{frm}-to-{to}", f"{step.__name__} failed: {exc.__class__.__name__}")
        # Convergence semantics: stamp the full version only when every step
        # succeeded. A failed step leaves the version short so the next status/
        # start re-runs the chain and retries it. Never raises; failure is audited.
        if failed == 0:
            _stamp(root, LAYOUT_VERSION)
            out["to"] = LAYOUT_VERSION
            out["upgraded"] = True
            _audit(root, "upgraded", f"layout {cur}->{LAYOUT_VERSION}; steps={len(ran)}")
        else:
            out["upgraded"] = False
            out["failed_steps"] = failed
            _audit(root, "upgrade-incomplete", f"layout stays {cur}; {failed} step(s) failed, will retry next run")
        out["ran"] = ran
    except Exception as exc:
        _audit(root, "upgrade-failed", exc.__class__.__name__)
    return out