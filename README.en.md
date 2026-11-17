# ag (AutoGovern)

[简体中文](README.md) | **English**

Local engineering delivery guardrails and stateless review foundation (MCP + CLI) for AI-assisted programming (Vibe Coding).

Current version: **v0.5.2**.

## What's New in v0.5.2

- **Single tickets and Markdown long tickets**: CLI and MCP default to `single`; ongoing goals explicitly select `long`, with a directly readable and editable `long.md` as the intent authority. Each round keeps its own original child ticket and sources.
- **One parent approval and verified delivery**: a long goal is approved once as a whole; later children within its approved scope inherit traceable parent authority without repeated human confirmation. Material changes need a new decision. Single tickets retain personal confirmation per ticket; independent review, isolation, verification and archiving remain required.
- **Explicit legacy migration**: legacy SQLite long tickets and historical exports remain available for read-only inspection. Only explicit migration creates the Markdown authority; the old HTML panel is no longer the default ticket creation or reading interface.

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
ag_status → ag_start → personal ticket approval (single) / first parent approval or inheritance (long) → ready → write only in <WORKTREE> → ag_verify → ag_finish
```

While a task is open, AG freezes tracked files on the canonical checkout. Windows adds a recoverable ACL deny-write entry for the current user; other systems clear the user-write bit. `ag_verify` refuses immediately when that checkout is dirty during an open task, records `canonical-dirty`, and does not run tests, probes, critic, or the switch.

Do **not** store long-lived tests in this repo. Worker checks belong in worktree `.ag-check/` (gitignored, discarded at finish). Old `tests/` is a standing answer key for the next AI; it is forbidden here.

Verification and review bind the same snapshot of product files and `.ag-check`. Receipts also record a `product_tree` without temporary checks to match the final commit. Snapshot calculation leaves the real index unchanged; staged or tracked `.ag-check` files are refused and never enter the product commit.

`ag_verify` runs an enrolled command only if one was set (other products may enroll a tiny smoke). This repo enrolls **no** test command. Then path-hit probes, and finally a single **switch** review call. A **configured** switch that is not passed (`rejected` / void unavailable, `sw-` id) refuses finish. Unconfigured or not-run switch does not. No enrolled tests and switch allow → `product` stays `undeclared`. Probe red still refuses finish.

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

## Intent Anchors & Startup Ticket (`<AG_HOME>/projects/<key>/ticket.md`)

Starting a default `single` task requires `<AG_HOME>/projects/<key>/ticket.md` in the ag home - the ticket never lives in the project tree - plus a locked result or at least one anchor. A legacy ticket (ticket.md / tickets/ / redlines.copy) left in the project is sha256-checked and moved into the new home once, with a readable migration record. That file is the single ticket intent authority. Explicit `long` tickets instead use the editable Markdown returned by `long read`; each round produces a sealed child review snapshot. `ag_start` reads it and refuses when it is missing; the error names `<AG_HOME>/projects/<key>/ticket.md`. `## 意图` is kept as written. Red lines from `## 红线` and from hard anchors are written back into `## 红线` and sealed into `<AG_HOME>/projects/<key>/redlines.copy`. An empty red-line list still writes that copy. `## 现场` is rewritten at start, verify, and finish, and those writes do not replace `## 意图` or the sealed red lines. `anchor_preview` is this document and `anchor_preview_path` is its absolute path. For a single ticket, show the document and wait for personal `confirm-map`. For a long goal, show the complete parent goal, promised results and applicable constraints for its first personal approval, with the reviewed `--preview <TOKEN>`. Later children within the approved scope inherit verified parent authority without another human confirmation. Each child still requires independent review, isolation and actual thaw before `ready`; verification and finish refuse missing or invalid authority.

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

- **Advice (`lift`)**: `lift-13` summarizes the task signal. `lift-14` stores an out-of-tree task snapshot. `lift-15` compares sealed red lines against the previous ticket (`dropped_redlines`). `lift-16` scans added diff lines for silent exception swallowing, production mock/fixture references, and placeholder stubs. `lift-17` suggests converging multi-touchpoint imports of new modules into a single mount point. `lift-18` tracks consecutive ticket sequence (`ticket_seq`) and enables strict anti-lazy review mode on round 3+ (`ticket_seq >= 3`).
- **Observation (`see`)**: `see-10` and `see-11` track repeated CSS selectors and ownership. `see-12` tracks suppression directive deltas (`suppression_delta`) and upward/reverse imports. `see-13` reports seat/pack health. `see-14` aggregates ticket history and recurring red lines from `<AG_HOME>/projects/<key>/tickets/`. `see-15` records the one-front-one-back (`ticket` + single `switch`) review token ledger (`saved_chars`, `script_digest`). `see-17` counts how often each review seat actually ran, and `see-18` reconciles the jsonl master against the `-last.json` caches and any legacy `ag.sqlite` rows.

---

## Critic Config (`config.json` → `critic`)

Inspect dynamically resolved config paths, readiness status (`reviewer_ready`, `api_key_present`), and the standard JSON template via CLI or `ag_status.onboarding.config_guide`:

```powershell
python -m ag config <PROJECT_ROOT>
```

Configuration lives in `<AG_HOME>/critic.json` (global) or the `critic` section of `<AG_HOME>/projects/<PROJECT_KEY>/config.json` (project override). Legacy per-project `critic.json` remains readable for migration. The API key stays in the environment variable named by `api_key_env`:

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

The default single ticket intent is `<AG_HOME>/projects/<key>/ticket.md` in the ag home (`ship-12`). `ag_start` seals `## 红线` into `<AG_HOME>/projects/<key>/redlines.copy` and archives each ticket snapshot to `<AG_HOME>/projects/<key>/tickets/<task_id>.md`.

AG uses a **0-Token deterministic script pre-screen + one-front-one-back (`ticket` at start, `switch` at verify) stateless DS review** architecture:
- **Front gate (`ship-13`, `ticket` seat)**: `ag_start` runs `ticket_prescreen` locally and launches a fresh stateless `ticket` thread (`thread_id`) scoring `goal_clarity`, `anchor_chain`, and `redline_focus` (`0-10`, pass `>= 7`) with an independent `understood_goal`. If configured and not `passed`, `confirm-map` soft-blocks worktree thawing; editing `<AG_HOME>/projects/<key>/ticket.md` and re-running `ag_start` while unconfirmed re-seals and re-reviews in place. On round 3+ (`lift-18`, `ticket_seq >= 3`), deterministic anti-lazy checks trigger one automatic retry on rubber-stamp/copied reviews (`lazy-review`).
- **Back gate (`see-15`, single `switch` seat)**: `ag_verify` runs `pack_prescreen` (syntax check, redline path/token collision scan, shortcut scan, `.ag-check/` assertion check) and pre-annotates `git diff` and windowed files (`> 12,000` chars slimmed to header + changed hunks) with exact `path:line` numbers. `ag_verify` calls `switch` once (mirroring `verify.critic` for compatibility and planting probes on reject), cutting token usage while preserving `path:line` evidence.

## Single tickets and Markdown long tickets

Omitting the type keeps the existing `single` workflow. Choose `long` explicitly for delivery across multiple rounds. A new long ticket uses an editable `long.md` as its intent authority: open and maintain the Markdown directly, without writing JSON or starting an HTML panel.

The first screen states the deliverable, completion criteria, current progress, blocker and next action, followed by a Mermaid main line. Folded sections retain applicable constraints, field evidence, round contributions, changes and pending proposals. Each opened child links to its own original `.md`; unopened work is labeled accordingly. Closed originals preserve their commitments, the user's words and sources, independently of later summaries.

At the start of each round, the AI reads the outline, relevant original ticket and real `delivery` receipts to recover unfinished commitments, branch reasons, return points and regression requirements. It updates only the necessary progress sections. The whole long goal needs approval only once. In-scope children inherit valid parent authorization while retaining independent ticket review and delivery checks. Routine progress, non-intent formatting, restarts and in-scope contribution decomposition preserve it; changed child contributions require renewed independent review. Material changes to the goal, constraints or approved result scope retain old→new, decision maker, reason, impact, return point and the scope of older evidence, then require independent review and a new personal decision. A thaw failure preserves approval and its source; retry through the formal recovery entry indicated by `delivery.next_action` without repeating business approval. A pending proposal stays pending; a passing child does not complete its parent.

Record file edits, business events and actual verification separately. Unverified changes remain unverified; reading or reformatting does not refresh verification time. Reload after an external edit. Stale tokens, invalid links, malformed documents and intent conflicts must be reported without overwriting external edits or silently dropping unknown sections.

Existing single tickets remain compatible. Legacy `long-goals.sqlite3` data and exports remain readable history. Explicit migration creates the new Markdown authority and marks the old authority as historical; failure preserves the original text and history. Never edit both authorities or inherit authorization that was never granted. The old HTML panel is no longer the default opening or reading path.

Use `python -m ag start <PROJECT_ROOT>` (MCP `ag_start(root="<PROJECT_ROOT>")`) to recover an active long ticket, retaining its task_id; inherited thaw failures retry this entry without another `confirm-map`. Check `delivery.authorization.mode`, `source_task_id`, `parent_proof` and actual readiness. `mode=inherited-long` identifies inheritance, while `approved` means valid authority. The child `long_authorization` receipt binds its parent proof to the current review; `intent_map_confirmed=false` continues to mean that the user did not personally confirm this child. `start-long-inheritance` directs activation and `recover-long-authorization` directs recovery; both use the same formal `start` entry. A first approval is still `user-confirm-map`. Status and delivery remain read-only.

CLI entry examples (single retains personal approval per ticket; long uses first parent approval followed by verified inheritance, with independent review for every child):

```powershell
# Omission keeps single; --ticket-type single is also explicit
python -m ag start <PROJECT_ROOT> --portrait "This round's independent delivery"

# Create the long ticket, read document_path and result IDs, then open that .md directly
python -m ag long create <PROJECT_ROOT> --goal-id department-report --title "Department expense report" --original "Deliver a reconcilable report from the expense CSV" --source-ref "user request source" --result "Read CSV without changing it; reject invalid input" --result "Reconcile department totals with the source" --result "Deliver the report using the confirmed template"
python -m ag long read <PROJECT_ROOT> department-report
python -m ag start <PROJECT_ROOT> --ticket-type long --goal-id department-report --result-id <RESULT_ID> --contribution "Contribution to the parent goal"
# An existing document can instead be selected with --long-file <LONG_MD>

# The user personally approves the whole parent goal once, using the displayed preview
python -m ag confirm-map <PROJECT_ROOT> --preview <TOKEN>
# After independently verifying and closing that child, open another in-scope child: no new confirm-map
python -m ag start <PROJECT_ROOT> --ticket-type long --goal-id department-report --result-id <NEXT_RESULT_ID> --contribution "Next contribution within the approved parent scope"
# Retry inherited authority/thaw on an active long ticket without creating a new task or asking for approval
python -m ag start <PROJECT_ROOT>

# Inspect legacy SQLite history, then explicitly migrate it
python -m ag long migration-candidate <PROJECT_ROOT> <LEGACY_GOAL_ID>
python -m ag long migrate <PROJECT_ROOT> <LEGACY_GOAL_ID> --expected-legacy-sha256 <SOURCE_SHA256>
```

CLI `long create/read/update/history/diff/package` and MCP `ag_long` share the same document, source checks and validation. MCP `ag_start` uses `ticket_type`, `goal_id`/`long_file`, `result_ids` and `contribution`. Incremental operations carry the freshly read `expected_revision` and, when needed, `expected_document_sha256`; reload and inspect the diff after conflicts. Direct Markdown prose editing does not require JSON.
