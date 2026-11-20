# ag (AutoGovern)

[简体中文](README.md) | **English**

Local engineering delivery guardrails and stateless review foundation (MCP + CLI) for AI-assisted programming (Vibe Coding).

Current version: **v0.5.2**.

## What's New in v0.5.2

- **Standard single-ticket delivery**: each ticket retains independent review, personal confirmation, isolation and verification. `continuation_of` carries reference information without granting authority.

Three orthogonal lanes that must never mix: **ship (交货)** · **lift (抬正确率)** · **see (看见)**.

Only `ship` may set `product` or refuse `finish`. `lift` and `see` provide advice or observation only.

---

## What's New in v0.4

After v0.3 (delivery guardrails + stateless review foundation), v0.4 makes ag learn your project over time, and keeps the state dir lean and recallable.

- **Structural checkup**: a language-agnostic kernel finds island files, phantom (declared-but-unused) dependencies, and reverse references; a multi-language adapter table (Python / TS / Go / Rust / Java) auto-selects per language actually present. Read-only facts, never blocks.
- **One root `config.json`**: all project switches in one file — review seat, checkup adapters, anti-bloat gate, and a 49-strategy listing (name / on-off / pluggable). `python -m ag config-show <PROJECT_ROOT>` prints a human-readable view.
- **Cross-session retrospective**: each ticket archives what it tried / found / did right / did wrong + lesson; a cumulative project redlines book is fed to the AI on every `ag_start`; `python -m ag retro <PROJECT_ROOT>` prints a human-readable report. A fresh session no longer starts from zero.
- **Anti-bloat gate**: seat process logs are dropped once the conclusion lands, the usage ledger rolls to a bounded window, and `python -m ag prune <PROJECT_ROOT>` compacts old residue to index lines — keep conclusions, cut process noise.
- **Versioned project state**: `<AG_HOME>/projects/<key>` is a local git repo tracking conclusions and config only, so accidental deletes are recoverable.
- **Self-governance human gate**: a ticket that modifies ag's own code, when rejected by switch, makes finish stop and wait for a manual `python -m ag approve-self <PROJECT_ROOT> <TASK_ID>` — never silently auto-approving changes to ag itself.

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
ag_status → ag_start → personal confirm-map → ready → write only in <WORKTREE> → ag_verify → ag_finish
```

While a task is open, AG freezes tracked files on the canonical checkout. Windows adds a recoverable ACL deny-write entry for the current user; other systems clear the user-write bit. `ag_verify` refuses immediately when that checkout is dirty during an open task, records `canonical-dirty`, and does not run tests, probes, critic, or the switch.

Do **not** store long-lived tests in this repo. Worker checks belong in worktree `.ag-check/` (gitignored, discarded at finish). Old `tests/` is a standing answer key for the next AI; it is forbidden here.

Verification and review bind the same snapshot of product files and `.ag-check`. Receipts also record a `product_tree` without temporary checks to match the final commit. Snapshot calculation leaves the real index unchanged; staged or tracked `.ag-check` files are refused and never enter the product commit.

`ag_verify` runs an enrolled command only if one was set (other products may enroll a tiny smoke). This repo enrolls **no** test command. Then path-hit probes, and finally a single **switch** review call. A **configured** switch that is not passed (`rejected` / void unavailable, `sw-` id) refuses finish. Unconfigured or not-run switch does not. No enrolled tests and switch allow → `product` stays `undeclared`. Probe red still refuses finish. A command probe times out after 30 s unless its observation sets `timeout_s` (an integer from 1 to 1800); invalid values are refused by `probe insert` and `calibrate`, and an invalid stored value makes the probe red.

`history-corrupt` means a line in `history/current.jsonl` or a `volume-*.jsonl` is not valid JSON, has the wrong schema, or fails its checksum. Readers skip that line (it never makes a record appear); `status` adds the `history-corrupt` hazard and lists `history_issues` (`path`, 1-based `line`); `delivery` adds a `history-corrupt` blocker and never offers `finish`. `start`, `verify`, `finish`, appends onto a bad `current.jsonl`, numbered (report id) writes and `prune` refuse with `<file> line <n>`. ag never deletes or rewrites the bad line: back it up, repair or remove the reported line by hand, then retry.

```powershell
python -m ag enroll <PROJECT_ROOT>
python -m ag config <PROJECT_ROOT>
python -m ag mcp
```

Critic config lives in `<AG_HOME>/critic.json` (default `~/.ag/critic.json`) or per-project `<AG_HOME>/projects/<PROJECT_KEY>/config.json`. The whole state dir is a local git repo tracking conclusions and config (not rolling logs); every `finish`/`abandon` auto-commits, so accidental deletes are recoverable. Audit: append-only `<seat>.jsonl` event logs. Task step chain (not in git): `<AG_HOME>/projects/<PROJECT_KEY>/tasks/<TASK_ID>.json` — one object with a `steps` array, appended at start / verify-refused / verify-tests / verify-probes / verify-switch / finish / finish-refused. `ag_status.timeline_path` points at the current or latest file. `ag critic-log` prints that timeline. `python -m ag config <PROJECT_ROOT>` outputs the structured configuration guide (`config_guide`) and readiness diagnostics.

---

## Strategy Lanes

- `ship` is the only delivery gate. It may set `product` and refuse `finish`.
- `lift` and `see` are advice/observation. They never set `product` or refuse `finish`.
- Strategy points are available through `ag lift` and `ag see` for an enrolled repository.

---

## Ticket packages

Write the package under `<AG_HOME>/projects/<key>/draft/`: human `ticket.md`, machine `spec.json` and pre-registered `checks/check_*.py` plus helpers. Enroll scaffolds a template with empty origin.user_words; fill it before start.

The human document requires four non-empty sections: 要做成什么, 怎样算做成, 不做什么, 需要你拍板的事. Results in spec have unique ids and text of at least 20 characters. Every result needs a target check; guards protect existing behavior. Checks must stay inside checks/, refer to declared results (or ["guard"]), and use target/guard kinds. scope.allow is non-empty; budget fields are positive integers. T4a validates their format; T7 owns runtime scope/budget enforcement. continuation_of comes only from spec.json and references a closed, personally confirmed ticket without transferring authority.

Start seals exact bytes under tickets/<task_id>/ and atomically writes seal.json with file hashes, source_head, opening baselines and ticket review. Baselines run sealed check paths in the frozen source_head worktree, using Python with cwd=worktree and a 300-second limit per check. Targets must fail, guards must pass. Reviewers receive the complete human document, spec, check sources and baseline tails. The three review dimensions and 7-point threshold remain unchanged.

The user personally runs confirm-map; AI never calls it. Only ready allows construction. Verify runs sealed checks, additional worktree .ag-check checks and registered project commands, then probes and switch review. Finish rechecks the seal and verified candidate. Sealed ticket.md is never rewritten with status information.

For changes before or after confirmation, edit draft/ and call start on the same ticket. revise-ticket-and-start directs this flow. Validate, run the new baseline on a clean source_head copy and prepare the seal first; only then freeze construction, archive the old seal in tickets/<id>.revisions/ and re-review. Preparation failures preserve the current seal, confirmation, permissions and code; a reviewer rejection keeps the new seal and construction frozen. Personal confirm-map and a fresh verify are required again. Unchanged drafts only resume; no revision or review is created.

Refusals: ticket-package-missing, ticket-md-invalid, spec-invalid (with field path), result-uncovered, invalid-continuation, baseline-target-green, baseline-guard-red, sealed-check-changed, seal-invalid, legacy-ticket-format. Legacy active tickets or invalid seals can still be abandoned; legacy ticket data is never migrated.

## Mandatory Worker Flow

Create a vendor-neutral worker dossier inside the active AG worktree:

```powershell
python -m ag worker-create <PROJECT_ROOT> --portrait "Done looks like ..." --anchor "keep auth behavior unchanged" --hard-anchor "do not run ag finish" --write-allow src/auth --write-allow src/core
```

Worker command guards are best-effort accident prevention, not a filesystem sandbox or a security boundary for untrusted processes.

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

- **Advice (`lift`)**: `lift-4` / `lift-11` run `AG_LIFT_CMD` through the shell, decode its output as UTF-8, and stop the whole process tree after `AG_LIFT_TIMEOUT` seconds (an integer from 1 to 1800; unset or invalid means 300), marking that finding `timed_out=true`; the `lift-2` linter uses the same limit. `lift-13` summarizes the task signal. `lift-14` stores an out-of-tree task snapshot. `lift-15` compares sealed red lines against the previous ticket (`dropped_redlines`). `lift-16` scans added diff lines for silent exception swallowing, production mock/fixture references, and placeholder stubs. `lift-17` suggests converging multi-touchpoint imports of new modules into a single mount point.
- **Observation (`see`)**: `see-10` and `see-11` track repeated CSS selectors and ownership. `see-12` tracks suppression directive deltas (`suppression_delta`) and upward/reverse imports. `see-13` reports seat/pack health. `see-14` aggregates ticket history and recurring red lines from `<AG_HOME>/projects/<key>/tickets/`. `see-15` records the one-front-one-back (`ticket` + single `switch`) review token ledger (`saved_chars`, `script_digest`). `see-17` counts how often each review seat actually ran, and `see-18` reconciles the jsonl master against the `-last.json` caches and any legacy `ag.sqlite` rows.

---

## Critic Config (`config.json` → `critic`)

Inspect dynamically resolved config paths, readiness status (`reviewer_ready`, `api_key_present`), and the standard JSON template via CLI or `ag_status.onboarding.config_guide`:

```powershell
python -m ag config <PROJECT_ROOT>
```

Configuration lives in `<AG_HOME>/critic.json` (global) or the `critic` section of `<AG_HOME>/projects/<PROJECT_KEY>/config.json` (project override). A project whose `config.json` has no `critic` section inherits the global file (upgrades no longer write a default section); any `critic` section, even just `{"enabled": false}`, overrides the global file. Legacy per-project `critic.json` remains readable for migration. The API key stays in the environment variable named by `api_key_env`:

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

## Ticket Document and One-Front-One-Back Review (`ship-12`, `ship-13`, `see-15`)

The default single ticket intent is `<AG_HOME>/projects/<key>/draft/ticket.md` in the ag home (`ship-12`). `ag_start` seals `## 红线` into `<AG_HOME>/projects/<key>/redlines.copy` and archives each ticket snapshot to `<AG_HOME>/projects/<key>/tickets/<task_id>.md`.

AG uses a **0-Token deterministic script pre-screen + one-front-one-back (`ticket` at start, `switch` at verify) stateless DS review** architecture:
- **Front gate (`ship-13`, `ticket` seat)**: `ag_start` runs `ticket_prescreen` locally and launches a fresh stateless `ticket` thread (`thread_id`) scoring `goal_clarity`, `anchor_chain`, and `redline_focus` (`0-10`, pass `>= 7`) with an independent `understood_goal`. If configured and not `passed`, `confirm-map` soft-blocks worktree thawing; editing `<AG_HOME>/projects/<key>/draft/ticket.md` and re-running `ag_start` while unconfirmed re-seals and re-reviews in place. Deterministic anti-lazy checks trigger one automatic retry on rubber-stamp/copied reviews (`lazy-review`).
- **Back gate (`see-15`, single `switch` seat)**: `ag_verify` runs `pack_prescreen` (syntax check, redline path/token collision scan, shortcut scan, `.ag-check/` assertion check) and pre-annotates `git diff` and windowed files (`> 12,000` chars slimmed to header + changed hunks) with exact `path:line` numbers. `ag_verify` calls `switch` once (mirroring `verify.critic` for compatibility and planting probes on reject), cutting token usage while preserving `path:line` evidence.


## Confirmed tickets and archived data

To change a confirmed ticket, edit draft/ and run start, obtain independent review and personal confirm-map again, then verify the revised package. Existing construction stays in place; old verification is invalidated.

For `long-ticket-retired`, use `abandon` to close the active ticket. Legacy long ticket data stays untouched in `<AG_HOME>` without migration: new code does not read, rewrite or delete `long/`, `long-goals.sqlite3` or historical records. Archived ticket queries provide a degraded view without granting authority.
