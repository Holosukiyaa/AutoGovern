# ag

Three lanes that must not mix: **ship (交货)** · **lift (抬正确率)** · **see (看见)**.

Only ship may set `product` or refuse `finish`. lift / see are advice or observation.

## Documentation & AI Entry Navigation

- 🧭 **AI & User Entry Anchor (`AGENTS.md`)**: [`AGENTS.md`](AGENTS.md)
- 📘 **Usage & 6-Step Workflow Guide**: [`docs/guide.md`](docs/guide.md)
- ⚙️ **Configuration Guide (`critic.json`, Env Vars & MCP)**: [`docs/configuration.md`](docs/configuration.md)
- 🛠️ **Troubleshooting Manual**: [`docs/troubleshooting.md`](docs/troubleshooting.md)
- 🤖 **Bundled AI Skill**: [`skills/ag-anchor/SKILL.md`](skills/ag-anchor/SKILL.md)

MCP delivery loop. Canonical checkout (`<PROJECT_ROOT>`) is not a work site.

```
ag_status → ag_start → confirm-map → write only in <WORKTREE> → ag_verify → ag_finish
```

While a task is open, AG freezes tracked files on the canonical checkout. Windows adds a recoverable ACL deny-write entry for the current user. Other systems clear the user-write bit. The read-only bit and the ACL are strong friction against accidental edits. They are not an absolute security boundary. `ag_verify` refuses immediately when that checkout is dirty during an open task, records `canonical-dirty`, and does not run tests, probes, critic, or the switch.

Do **not** store long-lived tests in this repo. Worker checks belong in worktree `.ag-check/` (gitignored, discarded at finish). Old `tests/` is a standing answer key for the next AI; it is forbidden here.

`ag_verify` runs an enrolled command only if one was set (other products may enroll a tiny smoke). This repo enrolls **no** test command. Then path-hit probes, then one read-only critic, then the **switch**. Critic is a layer before the switch: `rejected` does not refuse this ticket's finish. A **configured** switch that is not passed (`rejected` / void unavailable, `sw-` id) refuses finish. Unconfigured or not-run switch does not. No enrolled tests and switch allow → `product` stays `undeclared`. Probe red still refuses finish.

```
python -m ag enroll <PROJECT_ROOT>
python -m ag config <PROJECT_ROOT>
python -m ag mcp
```

Critic config lives in `<AG_HOME>/critic.json` (default `~/.ag/critic.json`) or per-project `<AG_HOME>/projects/<PROJECT_KEY>/critic.json`. Audit: sqlite `ag.sqlite`. Task step chain (not in git): `<AG_HOME>/projects/<PROJECT_KEY>/tasks/<TASK_ID>.json` — one object with a `steps` array, appended at start / verify-refused / verify-tests / verify-probes / verify-critic / verify-switch / finish / finish-refused. `ag_status.timeline_path` points at the current or latest file. `ag critic-log` prints that timeline. `python -m ag config <PROJECT_ROOT>` outputs the structured configuration guide (`config_guide`) and readiness diagnostics.

## Strategy lanes

- `ship` is the only delivery gate. It may set `product` and refuse `finish`.
- `lift` and `see` are advice/observation. They never set `product` or refuse `finish`.
- Strategy points are available through `ag lift` and `ag see` for an enrolled repository.

## Intent anchors

Starting a task requires the gitignored file `.data/ticket.md` on the canonical checkout, plus a locked result or at least one anchor. That file is the only intent document. `ag_start` reads it and refuses when it is missing; the error names `.data/ticket.md`. `## 意图` is kept as written. Red lines from `## 红线` and from hard anchors are written back into `## 红线` and sealed into `.data/redlines.copy`. An empty red-line list still writes that copy. `## 现场` is rewritten at start, verify, and finish, and those writes do not replace `## 意图` or the sealed red lines. `anchor_preview` is this document and `anchor_preview_path` is its absolute path. The first successful `ag_start` also returns `anchor_brief`, a short template, and does not include the skill text. Another `ag_start` or `ag_status` on that same ticket before `confirm-map` returns `skill`, the full `skills/ag-anchor/SKILL.md`. After confirmation those fields are omitted. Before any product file is written, the AI must show that document to the user and wait for explicit approval. AG freezes the worktree until `confirm-map`; `ag_status` reports `intent-map-unconfirmed` as a hazard; `ag_verify` and `ag_finish` refuse while the map is unconfirmed.

```text
anchor: keep the semantic workbench behavior unchanged
anchor: do not add a new CSS layer
```

`lift-12` reads these lines as attention anchors, not as a step plan. `anchor!:` is a hard anchor when it follows from an explicit user rule such as `必须`, `禁止`, `不要`, `must`, `forbidden`, or `do not`. The AI may propose a hard anchor, but may not invent one from its own guess.

`ag_start` reports an optional `subagent` object. AG does not bind to Codex, Grok, Claude, or any other worker implementation. A commander may use any subagent as an adapter: show the `anchor_preview`, wait for the user to call `confirm-map`, create 1-3 workers, then collect each `result.json`. Workers never run `ag_finish`, merge, modify anchors, or claim acceptance. `confirm-map` must be called by the user, not self-invoked by the AI.

Intent route, guard, default, and avoid are different layers:

- **Route anchors** are middle stations that carry attention toward the endpoint. They may be soft or hard, but they should not merely restate acceptance rules.
- Write route anchors as verb-bearing declarative sentences with at least 20 characters: name the object, the direction, and why the step moves toward the endpoint. They are directional landmarks, not bare slogans or task-list commands.
- **Guards** are mandatory acceptance rules. Pass them to `ag_start --guard` or MCP `guards`; they render beside the route, never as nodes on the START→END path.
- **Defaults** are negotiable choices. Pass them to `ag_start --default` or MCP `defaults`; they render beside the route and do not prove completion by themselves.
- **Avoid** keeps its separate zone: it prevents drift and is not a middle station toward the endpoint.

Anchor kinds remain compatible:


- `anchor:` soft attention; drift is allowed when disclosed.
- `anchor!:` hard rule from an explicit user/project rule.
- `anchor~:` discoverable unknown; investigate, then report the answer.
- `anchor?:` blocking unknown; ask one concise question before starting.
- `anchor=:` reasonable default chosen by the AI; disclose it.
- `anchor-:` avoid zone; crossing it requires a user-approved anchor revision.
- `anchorx:` obsolete anchor; keep the history and stop pursuing it.

## Mandatory worker flow

Create a vendor-neutral worker dossier inside the active AG worktree:

```powershell
python -m ag worker-create <PROJECT_ROOT> --portrait "Done looks like ..." --anchor "keep auth behavior unchanged" --hard-anchor "do not run ag finish" --write-allow src/auth --write-allow src/core
```

The dossier contains `task.json` and `TASK.md` under `<AG_HOME>/worktrees/<PROJECT_KEY>/<TASK_ID>.artifacts/workers/<WORKER_ID>/`. Any subagent CLI can implement it as an adapter. The worker writes `result.json` with schema `ag.worker.result.v1`, including `status`, `changed_files`, `anchor_receipt`, `evidence`, and `open_questions`. Read and validate it with:

```powershell
python -m ag worker-read <PROJECT_ROOT> <WORKER_ID>
```

`anchor_receipt` records attention, not acceptance. AG still decides delivery through `ag_verify` and `ag_finish`.
Every worker dossier carries the current `.data/ticket.md` text and its absolute path. AG allows at most 3 worker dossiers per task. `ag_verify` fails while any dossier is missing its `result.json`; the missing worker ids are returned as `verify.missing_worker_results` and `evidence.workers.missing_results`.

AG can launch a Grok dossier as an external worker provider:

```powershell
python -m ag worker-run <PROJECT_ROOT> <WORKER_ID> --provider grok
```

The provider is optional and vendor-neutral. It does not make Grok a Codex-native subagent; AG remains the commander and the delivery gate. `worker-run` streams stdout/stderr to the terminal while appending every line to that worker's `live.jsonl` beside the worktree. Use `python -m ag worker-log <PROJECT_ROOT> <WORKER_ID>` to tail that rolling output from another terminal. The command discovers `grok` from `PATH`, `~/.grok/bin`, or `AG_GROK_COMMAND`; `--timeout` is optional. Grok runs without its own subagents and with shell commands routed through `guard.py`; governance commands, `git commit/merge/rebase/push`, and scripts outside `--write-allow` are refused by the worker guard.

Configured critic and switch chats stream their incremental reasoning/content into `<AG_HOME>/projects/<PROJECT_KEY>/critic-live.jsonl` and `switch-live.jsonl`. Tail either stream with `python -m ag checker-log <PROJECT_ROOT> critic` or `... switch`. These files are append-only process evidence, not acceptance reports.

## Change-aware advice

`lift-13` summarizes the task signal from the portrait, touched files, HEAD, and verify exit. It reports `changed=true` only when that signal changes. `lift-14` stores a raw task snapshot under `AG_HOME`; it is not product evidence and does not enter the repository. `lift-15` compares sealed red lines against the previous ticket and surfaces `dropped_redlines` without blocking start or finish. `lift-16` scans added diff lines on non-test files for silent exception swallowing, production mock/fixture references, and placeholder stubs. `lift-17` detects newly added package directories and suggests converging multi-touchpoint imports into a single composition-root mount point. `lift-18` tracks consecutive ticket sequence (`ticket_seq`), enables strict anti-lazy review mode on round 3+ (`ticket_seq >= 3`), and records `last_thread_id`, `retried_lazy`, `scores`, and `redline_overlap_ratio` under `plug/lift-18/anti_lazy.json`.

## Symptom and ownership observation

`see-10` records repeated CSS selectors across files, including selector counts, `!important` counts, consumers, and co-change history. `see-11` turns those symptoms into an ownership table with definers, modifiers, overriders, and consumers. `see-12` tracks suppression directive deltas (`suppression_delta`) and upward/reverse imports across languages. `see-13` reports seat/pack health (`critic-live.jsonl` and `switch-live.jsonl` sizes, sealed redlines, and binary/oversize `.ag-check` exclusions). `see-14` aggregates ticket history and recurring red lines from `.data/tickets/` and `plug_dir`. `see-15` records the one-front-one-back (`ticket` + single `switch`) review token ledger (`ticket_pack_chars`, `raw_file_chars`, `slimmed_file_chars`, `saved_chars`, `script_short_circuit`, and `script_digest` summary) under `plug/see-15/token_ledger.json`.

## Critic config (`critic.json`)

Inspect dynamically resolved config paths, readiness status (`reviewer_ready`, `api_key_present`), and the standard JSON template via CLI or `ag_status.onboarding.config_guide`:

```powershell
python -m ag config <PROJECT_ROOT>
```

Configuration lives in `<AG_HOME>/critic.json` (global default, `~/.ag/critic.json`) or `<AG_HOME>/projects/<PROJECT_KEY>/critic.json` (per-project override). The file holds the seat endpoint, model, timeout, and the environment-variable name for the API key (`api_key_env`). The API key itself stays in that environment variable and is never written to `critic.json`:

```json
{
  "enabled": true,
  "endpoint": "https://api.deepseek.com/v1/chat/completions",
  "model": "deepseek-reasoner",
  "api_key_env": "AG_CRITIC_API_KEY",
  "timeout": 90,
  "worker_model": "",
  "allow_same_family": false
}
```

See [`docs/configuration.md`](docs/configuration.md) for full details.

## Skill installation

Install the bundled attention skill for Codex or Grok:

```powershell
python -m ag install-skill --target codex
python -m ag install-skill --target grok
```

## Ticket document and one-front-one-back review (`ship-12`, `ship-13`, `lift-18`, `see-15`)

The task intent is `.data/ticket.md` on the canonical checkout (`ship-12`). `.data/` is gitignored. `ag_start` must see that file, seals `## 红线` into `.data/redlines.copy`, and archives each ticket snapshot to `.data/tickets/<task_id>.md`. Status, verify, and finish rewrite `## 现场`, leave `## 意图` and the sealed `## 红线` in place, and update `.data/tickets/<task_id>.md`.

AG uses a **0-Token deterministic script pre-screen + one-front-one-back (`ticket` at start, `switch` at verify) stateless DS review** architecture:
- **Front gate (`ship-13`, `ticket` seat)**: `ag_start` runs `ticket_prescreen` locally (checking structure, positive/negative anchor chains, boilerplate redlines, `ticket_seq`, and cross-ticket overlap into `script_digest`) and launches a fresh stateless `ticket` thread (`thread_id`) scoring `goal_clarity`, `anchor_chain`, and `redline_focus` (`0-10`, pass `>= 7`) with an independent `understood_goal`. If configured and not `passed`, `confirm-map` soft-blocks worktree thawing; editing `.data/ticket.md` and re-running `ag_start` while unconfirmed re-seals and re-reviews in place. On round 3+ (`lift-18`, `ticket_seq >= 3`), deterministic anti-lazy checks trigger one automatic retry on rubber-stamp/copied reviews (`lazy-review`).
- **Back gate (`see-15`, single `switch` seat)**: `ag_verify` runs `pack_prescreen` (syntax check, redline path/token collision scan, shortcut scan, `.ag-check/` assertion check) and pre-annotates `git diff` and windowed files (`> 12,000` chars slimmed to header + changed hunks) with exact `path:line` numbers. `ag_verify` calls `switch` once (mirroring `verify.critic` for compatibility and planting probes on reject), cutting token usage while preserving `path:line` evidence.

`ag anchor-map` still writes a one-off text file outside the checkout when asked. It is not the task document, and status does not keep it updated.

`ag_verify` returns an `evidence` object with test status/tails, probe verdicts/tails, critic and switch outcomes/report ids/stores/models/`redlines`, the ticket path and preview, current attention anchor, worker result status, verified tree digest, and timings. Report the evidence, not only the report ids.

`ag_finish` returns `anchor_progress`: every anchor with id/kind/text, the absolute ticket path, and a reminder to compare the final result with the intent document before accepting delivery. Soft anchors are not marked complete automatically.
