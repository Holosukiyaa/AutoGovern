# ag

Four lanes that must not mix: **ship (交货)** · **heal (治病)** · **lift (抬正确率)** · **see (看见)**.

Only ship may set `product` or refuse `finish`. heal / lift / see are advice or observation.

MCP delivery loop. Canonical checkout is not a work site. While a task is open, tracked canonical files are read-only.

```
ag_status → ag_start → write only in worktree → ag_verify → ag_finish
```

Do **not** store long-lived tests in this repo. Worker checks belong in worktree `.ag-check/` (gitignored, discarded at finish). Old `tests/` is a standing answer key for the next AI; it is forbidden here.

`ag_verify` runs an enrolled command only if one was set (other products may enroll a tiny smoke). This repo enrolls **no** test command. Then path-hit probes, then one read-only critic, then the **switch**. Critic is a layer before the switch: `rejected` does not refuse this ticket's finish. A **configured** switch that is not passed (`rejected` / void unavailable, `sw-` id) refuses finish. Unconfigured or not-run switch does not. No enrolled tests and switch allow → `product` stays `undeclared`. Probe red still refuses finish.

```
ag enroll <repo>
ag mcp
```

Critic config lives in `~/.ag/projects/<key>/critic.json`. Audit: sqlite `ag.sqlite`. Task step chain (not in git): `~/.ag/projects/<key>/tasks/<task_id>.json` — one object with a `steps` array, appended at start / verify-tests / verify-probes / verify-critic / verify-switch / finish / finish-refused. `ag_status.timeline_path` points at the current or latest file. `ag critic-log` / `ag-gui.bat` (pick an enrolled repo) shows that timeline at the top.

## Strategy lanes

- `ship` is the only delivery gate. It may set `product` and refuse `finish`.
- `lift`, `heal`, and `see` are advice/observation. They never set `product` or refuse `finish`.
- Strategy points are available through `ag lift`, `ag heal`, and `ag see` for an enrolled repository.

## Intent anchors

Starting a task requires at least one anchor. `ag_start` refuses an empty portrait and returns the absolute paths to an automatically generated intent SVG and matching Unicode preview under `.ag-artifacts/anchor-maps/`; the Unicode preview is also returned as `anchor_preview`. The SVG marks `current_anchor` as current attention, never as anchor completion. Write anchors as lines in the portrait:

```text
anchor: keep the semantic workbench behavior unchanged
anchor: do not add a new CSS layer
```

`lift-12` reads these lines as attention anchors, not as a step plan. `anchor!:` is a hard anchor when it follows from an explicit user rule such as `必须`, `禁止`, `不要`, `must`, `forbidden`, or `do not`. The AI may propose a hard anchor, but may not invent one from its own guess.

`ag_start` reports an optional `subagent` object. AG does not bind to Codex, Grok, Claude, or any other worker implementation. A commander may use any subagent as an adapter: give that process the worker dossier, let it work only in the isolated AG worktree, then collect its `result.json`. Workers never run `ag_finish`, merge, modify anchors, or claim acceptance.

Anchor kinds are attention metadata, not a delivery gate:

- `anchor:` soft attention; drift is allowed when disclosed.
- `anchor!:` hard rule from an explicit user/project rule.
- `anchor~:` discoverable unknown; investigate, then report the answer.
- `anchor?:` blocking unknown; ask one concise question before starting.
- `anchor=:` reasonable default chosen by the AI; disclose it.
- `anchor-:` avoid zone; crossing it requires a user-approved anchor revision.
- `anchorx:` obsolete anchor; keep the history and stop pursuing it.

## Optional subagents

Create a vendor-neutral worker dossier inside the active AG worktree:

```powershell
python -m ag worker-create C:\repo --portrait "Done looks like ..." --anchor "keep auth behavior unchanged" --hard-anchor "do not run ag finish" --write-allow src/auth --write-allow tests/auth
```

The dossier contains `task.json` and `TASK.md` under `.ag-artifacts/workers/<worker-id>/`. Any subagent CLI can implement it as an adapter. The worker writes `result.json` with schema `ag.worker.result.v1`, including `status`, `changed_files`, `anchor_receipt`, `evidence`, and `open_questions`. Read and validate it with:

```powershell
python -m ag worker-read C:\repo <worker-id>
```

`anchor_receipt` records attention, not acceptance. AG still decides delivery through `ag_verify` and `ag_finish`.

## Change-aware advice

`lift-13` summarizes the task signal from the portrait, touched files, HEAD, and verify exit. It reports `changed=true` only when that signal changes. `lift-14` stores a raw task snapshot under `AG_HOME`; it is not product evidence and does not enter the repository.

## Symptom and ownership observation

`see-10` records repeated CSS selectors across files, including selector counts, `!important` counts, consumers, and co-change history. `see-11` turns those symptoms into an ownership table with definers, modifiers, overriders, and consumers. `heal-5` classifies them as noise, incident, risk, suspected, or confirmed. `heal-6` writes a treatment ticket for a confirmed item with `cut=false`; treatment itself must go through `ag start` and the ship lane.

## Skill installation

Install the bundled attention skill for Codex or Grok:

```powershell
python -m ag install-skill --target codex
python -m ag install-skill --target grok
```

## Anchor map

Render an SVG attention route from portrait anchor lines:

```powershell
python -m ag anchor-map --portrait "anchor: 先看见症状`nanchor!: 禁止自动开刀" --title "意图锚点图"
```

By default, generated maps go to `.ag-artifacts/anchor-maps/`, which is git-ignored. Use `--out` only when the user explicitly requests another location. The map widens with anchor count and keeps font size fixed. Nine or more anchors trigger a consolidation warning. During an active task `status` regenerates both views; after `verify`, the current-attention marker moves to the last route anchor.

`ag_verify` returns an `evidence` object with test status/tails, probe verdicts/tails, critic and switch outcomes/report ids/stores/models, the anchor SVG and Unicode paths/preview, current attention anchor, verified tree digest, and timings. Report the evidence, not only the report ids.

`ag_finish` returns `anchor_progress`: every anchor with id/kind/text, the absolute intent-SVG path, and a reminder to compare the final result with the intent map before accepting delivery. Soft anchors are not marked complete automatically.
