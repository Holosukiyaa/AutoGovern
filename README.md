# ag

Four lanes that must not mix: **ship (交货)** · **heal (治病)** · **lift (抬正确率)** · **see (看见)**.

Only ship may set `product` or refuse `finish`. heal / lift / see are advice or observation.

MCP delivery loop. Canonical checkout is not a work site.

```
ag_status → ag_start → write only in worktree → ag_verify → ag_finish
```

While a task is open, AG freezes tracked files on the canonical checkout. Windows adds a recoverable ACL deny-write entry for the current user. Other systems clear the user-write bit. The read-only bit and the ACL are strong friction against accidental edits. They are not an absolute security boundary. `ag_verify` refuses immediately when that checkout is dirty during an open task, records `canonical-dirty`, and does not run tests, probes, critic, or the switch.

Do **not** store long-lived tests in this repo. Worker checks belong in worktree `.ag-check/` (gitignored, discarded at finish). Old `tests/` is a standing answer key for the next AI; it is forbidden here.

`ag_verify` runs an enrolled command only if one was set (other products may enroll a tiny smoke). This repo enrolls **no** test command. Then path-hit probes, then one read-only critic, then the **switch**. Critic is a layer before the switch: `rejected` does not refuse this ticket's finish. A **configured** switch that is not passed (`rejected` / void unavailable, `sw-` id) refuses finish. Unconfigured or not-run switch does not. No enrolled tests and switch allow → `product` stays `undeclared`. Probe red still refuses finish.

```
ag enroll <repo>
ag mcp
```

Critic config lives in `~/.ag/projects/<key>/critic.json`. Audit: sqlite `ag.sqlite`. Task step chain (not in git): `~/.ag/projects/<key>/tasks/<task_id>.json` — one object with a `steps` array, appended at start / verify-refused / verify-tests / verify-probes / verify-critic / verify-switch / finish / finish-refused. `ag_status.timeline_path` points at the current or latest file. `ag critic-log` prints that timeline. `ag-config.bat` opens the checkout's `critic.json` and does not render the timeline.

## Strategy lanes

- `ship` is the only delivery gate. It may set `product` and refuse `finish`.
- `lift`, `heal`, and `see` are advice/observation. They never set `product` or refuse `finish`.
- Strategy points are available through `ag lift`, `ag heal`, and `ag see` for an enrolled repository.

## Intent anchors

Starting a task requires at least one anchor. `ag_start` refuses an empty portrait and writes one Unicode intent map beside the worktree at `~/.ag/worktrees/<key>/<task>.artifacts/anchor-maps/`; the same text is returned as `anchor_preview`, and its path is `anchor_preview_path`. The map marks `current_anchor` as current attention, never as anchor completion. Before any product file is written, the AI must show that Unicode text to the user and wait for explicit approval. AG freezes the worktree until `confirm-map`; `ag_status` reports `intent-map-unconfirmed` as a hazard; `ag_verify` and `ag_finish` refuse while the map is unconfirmed. AG copies the Unicode map into `AG_HOME/projects/<key>/anchor-maps/` and records an `anchor-preview` timeline step, so the evidence survives worktree cleanup.

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
python -m ag worker-create C:\repo --portrait "Done looks like ..." --anchor "keep auth behavior unchanged" --hard-anchor "do not run ag finish" --write-allow src/auth --write-allow tests/auth
```

The dossier contains `task.json` and `TASK.md` under `~/.ag/worktrees/<key>/<task>.artifacts/workers/<worker-id>/`. Any subagent CLI can implement it as an adapter. The worker writes `result.json` with schema `ag.worker.result.v1`, including `status`, `changed_files`, `anchor_receipt`, `evidence`, and `open_questions`. Read and validate it with:

```powershell
python -m ag worker-read C:\repo <worker-id>
```

`anchor_receipt` records attention, not acceptance. AG still decides delivery through `ag_verify` and `ag_finish`.
Every worker dossier carries the current Unicode intent map and its absolute path. AG allows at most 3 worker dossiers per task. `ag_verify` fails while any dossier is missing its `result.json`; the missing worker ids are returned as `verify.missing_worker_results` and `evidence.workers.missing_results`.

AG can launch a Grok dossier as an external worker provider:

```powershell
python -m ag worker-run C:\repo <worker-id> --provider grok
```

The provider is optional and vendor-neutral. It does not make Grok a Codex-native subagent; AG remains the commander and the delivery gate. `worker-run` streams stdout/stderr to the terminal while appending every line to that worker's `live.jsonl` beside the worktree. Use `python -m ag worker-log C:\repo <worker-id>` to tail that rolling output from another terminal. The command discovers `grok` from `PATH`, `~/.grok/bin`, or `AG_GROK_COMMAND`; `--timeout` is optional. Grok runs without its own subagents and with shell commands routed through `guard.py`; governance commands, `git commit/merge/rebase/push`, and scripts outside `--write-allow` are refused by the worker guard.

Configured critic and switch chats stream their incremental reasoning/content into `~/.ag/projects/<key>/critic-live.jsonl` and `switch-live.jsonl`. Tail either stream with `python -m ag checker-log C:\repo critic` or `... switch`. These files are append-only process evidence, not acceptance reports.

## Change-aware advice

`lift-13` summarizes the task signal from the portrait, touched files, HEAD, and verify exit. It reports `changed=true` only when that signal changes. `lift-14` stores a raw task snapshot under `AG_HOME`; it is not product evidence and does not enter the repository.

## Symptom and ownership observation

`see-10` records repeated CSS selectors across files, including selector counts, `!important` counts, consumers, and co-change history. `see-11` turns those symptoms into an ownership table with definers, modifiers, overriders, and consumers. `heal-5` classifies them as noise, incident, risk, suspected, or confirmed. `heal-6` writes a treatment ticket for a confirmed item with `cut=false`; treatment itself must go through `ag start` and the ship lane.

## Critic config

Open this checkout's `critic.json` in Notepad. The file holds the seat endpoint, model, timeout, and the environment-variable name for the API key. The key itself stays in that environment variable.

```powershell
.\ag-config.bat
.\ag-config.bat C:\path\to\another\checkout
```

A missing file is created as a template with `enabled` false. An existing file is left unchanged. Pass no argument to open the config for the checkout that contains the bat.

## Skill installation

Install the bundled attention skill for Codex or Grok:

```powershell
python -m ag install-skill --target codex
python -m ag install-skill --target grok
```

## Anchor map

Write a Unicode attention route from portrait anchor lines:

```powershell
python -m ag anchor-map --portrait "anchor: 先看见症状`nanchor!: 禁止自动开刀" --title "意图锚点图"
```

By default, a one-off map goes to `~/.ag/worktrees/<key>/anchor-maps/` as a `.txt` file, outside the checkout. Use `--out` only when the user explicitly requests another location. During an active task `status` rewrites that Unicode file; after `verify`, the current-attention marker moves to the last route anchor.

`ag_verify` returns an `evidence` object with test status/tails, probe verdicts/tails, critic and switch outcomes/report ids/stores/models, the Unicode anchor path and preview, current attention anchor, worker result status, verified tree digest, and timings. Report the evidence, not only the report ids.

`ag_finish` returns `anchor_progress`: every anchor with id/kind/text, the absolute Unicode map path, and a reminder to compare the final result with the intent map before accepting delivery. Soft anchors are not marked complete automatically.
