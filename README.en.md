# ag (AutoGovern)

[简体中文](README.md) | **English**

Local engineering delivery guardrails and stateless review foundation (MCP + CLI) for AI-assisted programming (Vibe Coding).

Three orthogonal lanes that must never mix: **ship (交货)** · **lift (抬正确率)** · **see (看见)**.

Only `ship` may set `product` or refuse `finish`. `lift` and `see` provide advice or observation only.

---

## Bundled AI Skills & Entry Navigation

- 🧭 **AI & User Entry Anchor (`AGENTS.md`)**: [`AGENTS.md`](AGENTS.md)
- 📘 **Usage & 6-Step Workflow Skill (`ag-guide`)**: [`skills/ag-guide/SKILL.md`](skills/ag-guide/SKILL.md)
- ⚙️ **Configuration Guide Skill (`ag-config`)**: [`skills/ag-config/SKILL.md`](skills/ag-config/SKILL.md)
- 🛠️ **Troubleshooting Manual Skill (`ag-troubleshooting`)**: [`skills/ag-troubleshooting/SKILL.md`](skills/ag-troubleshooting/SKILL.md)
- 🎯 **Intent Anchor & Ticket Skill (`ag-anchor`)**: [`skills/ag-anchor/SKILL.md`](skills/ag-anchor/SKILL.md)

---

## Core Delivery Loop

The canonical checkout (`<PROJECT_ROOT>`) is never a work site. All edits happen inside an isolated task worktree (`<WORKTREE>`):

```text
ag_status → ag_start → confirm-map → write only in <WORKTREE> → ag_verify → ag_finish
```

While a task is open, AG freezes tracked files on the canonical checkout. Windows adds a recoverable ACL deny-write entry for the current user; other systems clear the user-write bit. `ag_verify` refuses immediately when that checkout is dirty during an open task, records `canonical-dirty`, and does not run tests, probes, critic, or the switch.

Do **not** store long-lived tests in this repo. Worker checks belong in worktree `.ag-check/` (gitignored, discarded at finish). Old `tests/` is a standing answer key for the next AI; it is forbidden here.

`ag_verify` runs an enrolled command only if one was set (other products may enroll a tiny smoke). This repo enrolls **no** test command. Then path-hit probes, and finally a single **switch** review call. A **configured** switch that is not passed (`rejected` / void unavailable, `sw-` id) refuses finish. Unconfigured or not-run switch does not. No enrolled tests and switch allow → `product` stays `undeclared`. Probe red still refuses finish.

```powershell
python -m ag enroll <PROJECT_ROOT>
python -m ag config <PROJECT_ROOT>
python -m ag mcp
```

Critic config lives in `<AG_HOME>/critic.json` (default `~/.ag/critic.json`) or per-project `<AG_HOME>/projects/<PROJECT_KEY>/critic.json`. Audit: sqlite `ag.sqlite`. Task step chain (not in git): `<AG_HOME>/projects/<PROJECT_KEY>/tasks/<TASK_ID>.json` — one object with a `steps` array, appended at start / verify-refused / verify-tests / verify-probes / verify-switch / finish / finish-refused. `ag_status.timeline_path` points at the current or latest file. `ag critic-log` prints that timeline. `python -m ag config <PROJECT_ROOT>` outputs the structured configuration guide (`config_guide`) and readiness diagnostics.

---

## Strategy Lanes

- `ship` is the only delivery gate. It may set `product` and refuse `finish`.
- `lift` and `see` are advice/observation. They never set `product` or refuse `finish`.
- Strategy points are available through `ag lift` and `ag see` for an enrolled repository.

---

## Intent Anchors & Startup Ticket (`.data/ticket.md`)

Starting a task requires the locally ignored file `.data/ticket.md` on the canonical checkout (`<PROJECT_ROOT>/.data/ticket.md`), plus a locked result or at least one anchor. That file is the only intent document. `ag_start` reads it and refuses when it is missing; the error names `.data/ticket.md`. `## 意图` is kept as written. Red lines from `## 红线` and from hard anchors are written back into `## 红线` and sealed into `.data/redlines.copy`. An empty red-line list still writes that copy. `## 现场` is rewritten at start, verify, and finish, and those writes do not replace `## 意图` or the sealed red lines. `anchor_preview` is this document and `anchor_preview_path` is its absolute path. Before any product file is written, the AI must show that document to the user and wait for explicit approval. AG freezes the worktree until `confirm-map`; `ag_status` reports `intent-map-unconfirmed` as a hazard; `ag_verify` and `ag_finish` refuse while the map is unconfirmed.

```text
anchor: keep the semantic workbench behavior unchanged
anchor: do not add a new CSS layer
```

`lift-12` reads these lines as attention anchors, not as a step plan. `anchor!:` is a hard anchor when it follows from an explicit user rule such as `必须`, `禁止`, `不要`, `must`, `forbidden`, or `do not`. The AI may propose a hard anchor, but may not invent one from its own guess.

Anchor kinds:

- `anchor:` soft attention; drift is allowed when disclosed.
- `anchor!:` hard rule from an explicit user/project rule.
- `anchor~:` discoverable unknown; investigate, then report the answer.
- `anchor?:` blocking unknown; ask one concise question before starting.
- `anchor=:` reasonable default chosen by the AI; disclose it.
- `anchor-:` avoid zone; crossing it requires a user-approved anchor revision.
- `anchorx:` obsolete anchor; keep the history and stop pursuing it.

---

## Mandatory Worker Flow

Create a vendor-neutral worker dossier inside the active AG worktree:

```powershell
python -m ag worker-create <PROJECT_ROOT> --portrait "Done looks like ..." --anchor "keep auth behavior unchanged" --hard-anchor "do not run ag finish" --write-allow src/auth --write-allow src/core
```

The dossier contains `task.json` and `TASK.md` under `<AG_HOME>/worktrees/<PROJECT_KEY>/<TASK_ID>.artifacts/workers/<WORKER_ID>/`. The worker writes `result.json` with schema `ag.worker.result.v1`, including `status`, `changed_files`, `anchor_receipt`, `evidence`, and `open_questions`. Read and validate it with:

```powershell
python -m ag worker-read <PROJECT_ROOT> <WORKER_ID>
```

AG can launch a Grok dossier as an external worker provider:

```powershell
python -m ag worker-run <PROJECT_ROOT> <WORKER_ID> --provider grok
```

Configured critic and switch chats stream their incremental reasoning/content into `<AG_HOME>/projects/<PROJECT_KEY>/critic-live.jsonl` and `switch-live.jsonl`. Tail either stream with `python -m ag checker-log <PROJECT_ROOT> critic` or `... switch`.

---

## Change-Aware Advice & Observation (`lift` & `see`)

- **Advice (`lift`)**: `lift-13` summarizes the task signal. `lift-14` stores an out-of-tree task snapshot. `lift-15` compares sealed red lines against the previous ticket (`dropped_redlines`). `lift-16` scans added diff lines for silent exception swallowing, production mock/fixture references, and placeholder stubs. `lift-17` suggests converging multi-touchpoint imports of new modules into a single mount point. `lift-18` tracks consecutive ticket sequence (`ticket_seq`) and enables strict anti-lazy review mode on round 3+ (`ticket_seq >= 3`).
- **Observation (`see`)**: `see-10` and `see-11` track repeated CSS selectors and ownership. `see-12` tracks suppression directive deltas (`suppression_delta`) and upward/reverse imports. `see-13` reports seat/pack health. `see-14` aggregates ticket history and recurring red lines from `.data/tickets/`. `see-15` records the one-front-one-back (`ticket` + single `switch`) review token ledger (`saved_chars`, `script_digest`).

---

## Critic Config (`critic.json`)

Inspect dynamically resolved config paths, readiness status (`reviewer_ready`, `api_key_present`), and the standard JSON template via CLI or `ag_status.onboarding.config_guide`:

```powershell
python -m ag config <PROJECT_ROOT>
```

Configuration lives in `<AG_HOME>/critic.json` (global default, `~/.ag/critic.json`) or `<AG_HOME>/projects/<PROJECT_KEY>/critic.json` (per-project override). The API key stays in the environment variable named by `api_key_env` and is never written to `critic.json`:

```json
{
  "enabled": true,
  "endpoint": "https://api.deepseek.com",
  "model": "deepseek-chat",
  "api_key_env": "AG_CRITIC_API_KEY",
  "timeout": 60,
  "worker_model": "claude",
  "allow_same_family": false
}
```

See [`skills/ag-config/SKILL.md`](skills/ag-config/SKILL.md) for full details.

---

## Skill Installation

Install all 4 bundled AG skills (`ag-anchor`, `ag-guide`, `ag-config`, `ag-troubleshooting`) for Codex or Grok:

```powershell
python -m ag install-skill --target codex
python -m ag install-skill --target grok
```

---

## Ticket Document and One-Front-One-Back Review (`ship-12`, `ship-13`, `lift-18`, `see-15`)

The task intent is `.data/ticket.md` on the canonical checkout (`ship-12`). `ag_start` seals `## 红线` into `.data/redlines.copy` and archives each ticket snapshot to `.data/tickets/<task_id>.md`.

AG uses a **0-Token deterministic script pre-screen + one-front-one-back (`ticket` at start, `switch` at verify) stateless DS review** architecture:
- **Front gate (`ship-13`, `ticket` seat)**: `ag_start` runs `ticket_prescreen` locally and launches a fresh stateless `ticket` thread (`thread_id`) scoring `goal_clarity`, `anchor_chain`, and `redline_focus` (`0-10`, pass `>= 7`) with an independent `understood_goal`. If configured and not `passed`, `confirm-map` soft-blocks worktree thawing; editing `.data/ticket.md` and re-running `ag_start` while unconfirmed re-seals and re-reviews in place. On round 3+ (`lift-18`, `ticket_seq >= 3`), deterministic anti-lazy checks trigger one automatic retry on rubber-stamp/copied reviews (`lazy-review`).
- **Back gate (`see-15`, single `switch` seat)**: `ag_verify` runs `pack_prescreen` (syntax check, redline path/token collision scan, shortcut scan, `.ag-check/` assertion check) and pre-annotates `git diff` and windowed files (`> 12,000` chars slimmed to header + changed hunks) with exact `path:line` numbers. `ag_verify` calls `switch` once (mirroring `verify.critic` for compatibility and planting probes on reject), cutting token usage while preserving `path:line` evidence.
