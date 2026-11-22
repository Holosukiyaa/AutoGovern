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

## Human presence and authorization

Only the user runs `confirm-map` and `approve-self` in their own terminal. AI hands over the CLI command and waits. The MCP tool `ag_confirm_map` has been removed. After existing state checks, stderr shows the sealed human ticket, machine summary and a four-character code. The user has three attempts, ignoring case and surrounding whitespace; stdout remains a single JSON receipt.

Windows checks GetConsoleMode on the stdin handle only; POSIX requires both os.isatty(0) and termios.tcgetattr(0). A non-console caller gets `human-console-required`; three incorrect codes produce `human-code-mismatch`. Git Bash/mintty and Windows Terminal still need human testing; use a personal PowerShell/cmd window if refused, or try winpty from Git Bash.

`AG_SYNTHETIC_CONFIRM=1` is test-only and works only when the resolved AG_HOME is below this process's tempfile.gettempdir(). It still prints the screen, skips the code and records a synthetic proof. The real default AG_HOME never accepts synthetic confirmation. Authorization requires both the task flag and a confirmation event matching authorization_identity with a valid proof. Synthetic proofs become invalid outside temp. A flag without such an event yields `authorization-unproven`; old confirmations are not migrated.

Known boundary: this prevents casual approval through AI tools; it does not prevent deliberate console fabrication, keystroke injection or history rewriting (history hashes are not keyed). Personal passphrases (scheme D) remain deferred.

## Site checks, andon and recovery

Pull the andon instead of working around scope. Each CLI command and MCP tool call checks an active ready site first; status may stop construction but never grants authority. The site block records changed files, sorted out_of_scope paths, budget usage and reminders. Changes are relative to source_head, include untracked files and exclude .ag-check/. Deny takes priority over allow/docs. Globs support exact files and ** across directories. Usage is the greater of file-count and added-plus-removed-line ratios: record below 70%, remind at 70% and above 100%, stop above 150%; scope violations stop immediately. Observed product changes are recorded in the worktree trail described below.

Use `andon <root> --reason "why work is blocked"` to stop deliberately. A site-stopped event and task.site_stop preserve kind, reason and evidence; the worktree is frozen, readiness is stopped and next_action is handoff. Verify, finish and workers refuse site-stopped. Abandon, andon, handoff, backbrief and confirm-map do not trigger checks.

Two ways out: use `handoff <root>` for an objective brief under tickets/<id>.handoff/, with the original ticket, result/check status, file list, budget, stop reason and next-session prompt. The receiving session supplies a JSON backbrief via `backbrief <root> --file <json>`: out_of_scope must exactly match current facts, goal needs at least 20 characters and next must be nonempty. Mismatch reports backbrief-mismatch and stays frozen. A correct backbrief checks the existing T5 authorization before thawing, clears the stop and records site-resumed; it grants no new authority. Remaining violations stop again on the next call. Alternatively edit draft/, run start for independent re-review and ask the user to confirm-map; successful confirmation clears the stop without losing construction.

MCP exposes ag_andon, ag_handoff and ag_backbrief. AI may backbrief, though a fresh session is recommended. Checks happen only when ag is called, including before verify; they cannot observe an agent that never calls ag.

## Worktree trail and extraneous additions

Site inspections and the start of verify append changed product snapshots to `<AG_HOME>/projects/<key>/tickets/<id>.trail.jsonl`, preserving them after ticket closure. Each snapshot records its time, command, product tree and per-file added/deleted lines, including untracked files and excluding `.ag-check`. An unchanged product tree produces no new row. Only calls to ag are observed; intermediate edits between calls are invisible. A temporary index keeps the real staging area unchanged; snapshots never enter history.

The switch receives `trajectory` (snapshots, time span, per-file rewrites/first appearance, created-then-deleted and withdrawn out-of-scope files, stops) as reference only, never a rejection reason on its own. Its `extraneous` evidence lists new files, unreferenced new source files using the configured adapter's reference rules, and draft-like names. Every new file and function must identify the `spec.results` item it serves; unexplained additions fail the extraneous review. Existing review and site-stop rules continue to apply.

## Context observations

`context_burden` estimates tracked files at source_head matching allow minus deny plus one-hop references using the structure adapter ref_patterns (falling back to exam neighbors when unconfigured); it does not block, impose thresholds or require splitting tickets. It is saved with the ticket and shown in ticket review, status and delivery. `est_tokens` is a rough estimate using the measured chars_per_token ratio described below, rounded up (zero for empty input).

Review history payloads record `usage` (prompt_tokens, completion_tokens, total_tokens, cached_tokens, calls and per_call attempts); streaming tail chunks and normal JSON are supported. Missing or malformed usage is null and never changes the verdict; request parameters stay unchanged. Switch `exam_size` records actual system/user sent_chars, raw_chars with omitted file/check/diff text restored, and truncated_files. Verify exposes `context` with estimate, measured usage/exam_size and actual_scope recomputed from actual changes. `context_trend` reads the newest ten switch events from history, with nulls for older missing fields. These are observations only, with no new hazards or gates; truncation and review rules stay unchanged.

## Entropy observations and slimming references

`entropy` records product added/deleted/net lines, new files, shortcuts, suppression additions/removals, broad excepts, parallel names and same-name files against source_head, including untracked files and excluding `.ag-check`. Existing advice rules classify shortcuts and suppressions; each evidence list contains at most 10 items. One ledger is shared by the switch exam, verify output and switch history. `entropy_trend` reads the newest 10 switch ledgers, with nulls for old missing fields. `budget_actual` uses the T7 site calculation; `budget_reference` lists the newest 10 distinct tickets, using each ticket's latest review and kind.

`slim_reminder` suggests a slimming ticket after 8 non-slim tickets or 800 net product lines since the last finished slim ticket; it reads finish history, excludes abandoned tickets and resets after a slim finish. With no slim history, it starts at the earliest package ticket. It never adds hazards or changes readiness/next_action. All these observations are reference only, with no new gate or review dimension.

`chars_per_token` is the median sent_chars/prompt_tokens of the latest 10 valid switch measurements; ratio_source is history, or default with 4.0 when none exist. Both opening context_burden and actual_scope use ceil(total_chars / chars_per_token); context_burden does not block. Saved opening estimates retain their ratio.

## Root causes for fix tickets

Only `kind=fix` requires `root_cause` with at least 20 characters after trimming; an absent or shorter value is rejected as `spec-invalid` naming `root_cause`. Describe where and why the failure occurs, not just the symptom. Ticket review puts symptom-only explanations in doubts and fails goal_clarity. The switch receives the verbatim root_cause at the top level and checks each change against it; symptom-level checks, fallbacks or special cases fail with the changed path:line as evidence. Feature and slim tickets skip this requirement; all other review rules stay unchanged.

## Graduated checks

Declare `graduate: [{"file": "checks/check_x.py"}]` in spec.json to graduate a target after a successful merge; optional task references an already merged ticket, and optional area is a nonempty relative glob list. The default area is the source ticket's scope.allow. A backfilled target runs during verify before graduation. Graduated guards only protect behavior; they are not evidence that a new ticket is complete.

The guard id is grad-<source-task>-<check-stem> (at most 64 characters). Its sealed_check observation executes the original sealed script with Python -B, after checking all sealed checks and helpers against seal.json (ignoring __pycache__). Changed, missing or extra files report guard-tampered without executing the script. Areas use site.matches globs, and graduated guards never age into archives. Plain probes keep their existing matching and lifetime rules.

Only a ticket's `retires: [{"id": "grad-...", "reason": "at least 20 characters"}]` can retire these guards: verify skips the named guards, returns retired_guards, and successful merge removes them with an audit. Abandon does not register or retire anything. Direct probe drop reports guard-graduated. `guard_cost` sums graduated guards' latest runtimes and suggests a retires ticket at 600 seconds; it never changes hazards, readiness or next_action. No scripts are copied and no guards_dir configuration is needed.
