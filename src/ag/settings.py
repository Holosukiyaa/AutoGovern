"""One root config per project: config.json is the single door a user opens.

Four sections live here: critic (review seat), structure (checkup adapter),
prune (anti-bloat gate), plugins (per-strategy on/off). All modules read through
load_settings(); nothing reads critic.json / adapter.json / managed.json off[]
directly anymore. Old layouts migrate automatically, leave one migration.jsonl
line, and the migration is idempotent.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .managed import ag_home, project_key, real_root
from .store import append_project_jsonl, project_dir

SETTINGS_NAME = "config.json"

# Defaults for each section; a section is "present" only when the user or a
# migration actually wrote it, so an untouched project keeps a tiny file.
_CRITIC_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "endpoint": "https://api.deepseek.com",
    "model": "deepseek-chat",
    "api_key_env": "DEEPSEEK_API_KEY",
    "timeout": 60,
    "worker_model": "",
    "allow_same_family": False,
}
_PRUNE_DEFAULTS: dict[str, Any] = {"usage_max_bytes": 200 * 1024, "usage_keep_bytes": 128 * 1024}

# Built-in per-language checkup adapters (the "用到什么语言就专门写一个适配器" table).
# Each maps a language to its source_exts / ref_patterns / dep manifest. entry_files
# are intentionally empty by default: the user fills in the real doors per repo.
_BUILTIN_ADAPTERS: dict[str, dict[str, Any]] = {
    "python": {
        "source_exts": [".py"],
        "entry_files": [],
        "ref_patterns": ["(?:^|\\s)from\\s+([\\w.]+)\\s+import", "(?:^|\\s)import\\s+([\\w.]+)"],
        "dep_manifest": "pyproject.toml",
        "dep_pattern": "^\\s*name\\s*=\\s*\"([^\"]+)\"",
    },
    "typescript": {
        "source_exts": [".ts", ".tsx", ".js", ".jsx"],
        "entry_files": [],
        "ref_patterns": [
            "import\\s+(?:[\\w{}*\\s,]+\\s+from\\s+)?['\"]([^'\"]+)['\"]",
            "require\\(\\s*['\"]([^'\"]+)['\"]\\s*\\)",
            "import\\(\\s*['\"]([^'\"]+)['\"]\\s*\\)",
        ],
        "dep_manifest": "package.json",
        "dep_pattern": "\"([^\"]+)\"\\s*:\\s*\"[\\^~]?[0-9]",
        "dep_section": "dependencies",
    },
    "go": {
        "source_exts": [".go"],
        "entry_files": [],
        "ref_patterns": ["^\\s*(?:[\\w.]+\\s+)?\"([^\"]+)\""],
        "dep_manifest": "go.mod",
        "dep_pattern": "^\\s*([\\w./-]+)\\s+v[0-9]",
    },
    "rust": {
        "source_exts": [".rs"],
        "entry_files": [],
        "ref_patterns": ["^\\s*use\\s+([\\w:]+)", "^\\s*mod\\s+([\\w]+)"],
        "dep_manifest": "Cargo.toml",
        "dep_pattern": "^([\\w-]+)\\s*=",
    },
    "java": {
        "source_exts": [".java"],
        "entry_files": [],
        "ref_patterns": ["^\\s*import\\s+(?:static\\s+)?([\\w.]+)"],
        "dep_manifest": "pom.xml",
        "dep_pattern": "<artifactId>([^<]+)</artifactId>",
    },
}


def default_adapters() -> dict[str, dict[str, Any]]:
    """A fresh copy of the built-in language adapter table."""
    return {lang: dict(cfg) for lang, cfg in _BUILTIN_ADAPTERS.items()}


def settings_path(root: Path) -> Path:
    return project_dir(real_root(root)) / SETTINGS_NAME


def _read(path: Path) -> dict[str, Any] | None:
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return blob if isinstance(blob, dict) else None


def _write(path: Path, blob: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _audit(root: Path, action: str, detail: str) -> None:
    try:
        append_project_jsonl(real_root(root), "migration.jsonl", {"action": action, "detail": detail})
    except Exception:
        import sys

        sys.stderr.write(f"ag: settings migration audit write failed for {action}; not logged\n")


def _legacy_critic(root: Path) -> dict[str, Any] | None:
    blob = _read(project_dir(real_root(root)) / "critic.json")
    return blob


def _legacy_adapter(root: Path) -> dict[str, Any] | None:
    return _read(project_dir(real_root(root)) / "adapter.json")


def _legacy_off(root: Path) -> list[str]:
    try:
        from .managed import lookup_project

        item = lookup_project(real_root(root))
    except Exception:
        return []
    return [str(x) for x in ((item or {}).get("off") or [])]


def _catalog_listing(off: list[str]) -> dict[str, Any]:
    """Build the human-readable per-lane strategy listing from the SQLite catalog.

    Each entry: name / on / pluggable / story. `off` marks a strategy off by code.
    Falls back to an empty mapping when the catalog DB is unavailable.
    """
    off_set = {str(x) for x in off}
    lanes: dict[str, Any] = {}
    try:
        from . import catalog as _catalog

        for lane in ("ship", "lift", "see"):
            rows = {}
            for item in _catalog.list_lane(lane):
                code = item["code"]
                seq = str(item["seq"])
                rows[seq] = {
                    "code": code,
                    "name": item["name"],
                    "on": code not in off_set,
                    "pluggable": bool(item["pluggable"]),
                    "story": item.get("story") or "",
                }
            lanes[lane] = rows
    except Exception:
        return {}
    return lanes


def _migrate(root: Path, blob: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Fold legacy files into the root config. Returns (blob, migrated?). Idempotent."""
    root = real_root(root)
    base = project_dir(root)
    changed = False

    removed: list[str] = []
    if "critic" not in blob:
        legacy = _legacy_critic(root)
        if legacy is not None:
            merged = dict(_CRITIC_DEFAULTS)
            merged.update({k: v for k, v in legacy.items() if k in _CRITIC_DEFAULTS})
            blob["critic"] = merged
            changed = True
            removed.append("critic.json")
    # structure: always converge to the multi-language adapters table
    sec_struct = blob.get("structure")
    if not isinstance(sec_struct, dict) or "adapters" not in sec_struct:
        # legacy single adapter (from adapter.json or an old flat structure section)
        legacy = sec_struct if isinstance(sec_struct, dict) and sec_struct else _legacy_adapter(root)
        adapters = default_adapters()
        if legacy:
            # fold the old single adapter in as the python entry (field-equivalent)
            adapters["python"] = {k: v for k, v in legacy.items() if not str(k).startswith("_")}
        enabled = bool(sec_struct.get("enabled")) if isinstance(sec_struct, dict) and "enabled" in sec_struct else True
        blob["structure"] = {"enabled": enabled, "adapters": adapters}
        changed = True
        if not isinstance(sec_struct, dict):
            removed.append("adapter.json")
    # plugins: always converge to a full catalog listing (name/on/pluggable/story per strategy)
    sec_plugins = blob.get("plugins")
    if not isinstance(sec_plugins, dict) or "lanes" not in sec_plugins:
        off = _legacy_off(root) if not isinstance(sec_plugins, dict) else [str(x) for x in (sec_plugins.get("off") or [])]
        blob["plugins"] = {"off": sorted(set(off)), "lanes": _catalog_listing(off)}
        changed = True
    if "prune" not in blob:
        blob["prune"] = dict(_PRUNE_DEFAULTS)

    if changed:
        blob["schema"] = "ag.config.v2"
        _write(settings_path(root), blob)
        # remove the folded legacy files so no corpse remains; never touch anything else
        for name in removed:
            try:
                (base / name).unlink()
            except OSError:
                pass
        _audit(root, "migrate-to-config", "folded+removed " + ",".join(removed) + " into config.json" if removed else "folded managed off[] into config.json")
    return blob, changed


def load_settings(root: Path) -> dict[str, Any]:
    """Read the root config, migrating any legacy layout first. Never raises on missing files."""
    root = real_root(root)
    blob = _read(settings_path(root)) or {}
    blob, _ = _migrate(root, blob)
    return blob


def get_section(root: Path, name: str) -> dict[str, Any]:
    blob = load_settings(root)
    sec = blob.get(name)
    return dict(sec) if isinstance(sec, dict) else {}


def plugin_off(root: Path) -> list[str]:
    """The single source of truth for per-strategy on/off (replaces managed off[])."""
    sec = get_section(root, "plugins")
    off = sec.get("off")
    return sorted({str(x) for x in off}) if isinstance(off, list) else []


def set_plugin_off(root: Path, off: list[str]) -> None:
    root = real_root(root)
    blob = _read(settings_path(root)) or {}
    blob, _ = _migrate(root, blob)
    off_sorted = sorted({str(x) for x in off})
    sec = blob.setdefault("plugins", {})
    sec["off"] = off_sorted
    # keep the human-readable listing's on-flags in sync with the off array
    lanes = sec.get("lanes")
    if isinstance(lanes, dict):
        off_set = set(off_sorted)
        for lane_rows in lanes.values():
            if isinstance(lane_rows, dict):
                for row in lane_rows.values():
                    if isinstance(row, dict) and "code" in row:
                        row["on"] = str(row["code"]) not in off_set
    blob["schema"] = "ag.config.v2"
    _write(settings_path(root), blob)


def prune_limits(root: Path) -> tuple[int, int]:
    sec = get_section(root, "prune")
    try:
        max_b = int(sec.get("usage_max_bytes") or _PRUNE_DEFAULTS["usage_max_bytes"])
        keep_b = int(sec.get("usage_keep_bytes") or _PRUNE_DEFAULTS["usage_keep_bytes"])
    except (TypeError, ValueError):
        max_b, keep_b = _PRUNE_DEFAULTS["usage_max_bytes"], _PRUNE_DEFAULTS["usage_keep_bytes"]
    return max_b, max(0, keep_b)


def collect_plug_state(root: Path) -> dict[str, Any]:
    """Gather the scattered plug/<lane>-<seq>/ runtime folders into one mapping (in-memory)."""
    base = project_dir(real_root(root)) / "plug"
    state: dict[str, Any] = {}
    if not base.is_dir():
        return state
    for folder in sorted(p for p in base.iterdir() if p.is_dir()):
        files = {}
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                rel = f.relative_to(folder).as_posix()
                try:
                    files[rel] = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    files[rel] = {"_raw_bytes": int(f.stat().st_size)}
        state[folder.name] = files
    return state


def collapse_plug_state(root: Path) -> dict[str, Any]:
    """Move plug/<lane>-<seq>/* into one plug-state.json, then remove the folders. Idempotent."""
    root = real_root(root)
    base = project_dir(root) / "plug"
    if not base.is_dir():
        return {"collapsed": [], "bytes": 0}
    state = collect_plug_state(root)
    out = project_dir(root) / "plug-state.json"
    _write(out, {"schema": "ag.plug-state.v1", "folders": state})
    import shutil

    collapsed: list[str] = []
    total = 0
    for folder in sorted(p for p in base.iterdir() if p.is_dir()):
        size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
        shutil.rmtree(folder)
        collapsed.append(folder.name)
        total += size
    try:
        base.rmdir()
    except OSError:
        pass
    _audit(root, "collapse-plug-state", f"{len(collapsed)} folders -> plug-state.json ({total}B)")
    return {"collapsed": collapsed, "bytes": total}