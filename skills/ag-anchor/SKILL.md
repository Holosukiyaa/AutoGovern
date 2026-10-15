---
name: ag-anchor
description: >
  Use for any ag-governed delivery task, especially when onboarding a user,
  configuring critic.json, or before ag_start when the user's one-sentence
  request hides a route. Extract user-facing intent anchors with positive and
  negative/boundary chains, keep them as attention rather than a step plan,
  persist them through ag, and disclose deviations. Also use when the user says
  锚点, 意图锚点, route, 配置 ag, or when a later suggestion conflicts with an
  existing anchor. This skill does not replace ag; delivery still goes through
  ag_start → confirm-map → work in <WORKTREE> → ag_verify → ag_finish.
---

# ag intent anchors & AI delivery guide

Intent anchors make the user's hidden route explicit without turning it into a
step plan. `ag` remembers them in task state; the AI must read them at the
start, while working, and before verification.

## Documentation & Variable Path Conventions

When assisting the user or diagnosing issues, consult the repository documentation:
- **Top-level AI & User Entry**: [`AGENTS.md`](../../AGENTS.md)
- **Usage & 6-Step Workflow Guide**: [`docs/guide.md`](../../docs/guide.md)
- **Configuration Guide (`critic.json` & MCP)**: [`docs/configuration.md`](../../docs/configuration.md)
- **Troubleshooting Manual**: [`docs/troubleshooting.md`](../../docs/troubleshooting.md)

Always use portable variable placeholders instead of hardcoded personal directory paths:
- `<PROJECT_ROOT>`: Target repository root (canonical checkout, frozen read-only during active tasks)
- `<AG_REPO_ROOT>`: `ag` repository root (when running from source)
- `<WORKTREE>`: Active isolated task worktree (`<AG_HOME>/worktrees/<PROJECT_KEY>/<TASK_ID>`)
- `<AG_HOME>`: `ag` state and configuration directory (default `~/.ag`)
- `<PYTHON_EXECUTABLE>`: Python interpreter path (e.g., `python`)

## AI Onboarding & Configuration Guide

When a user first sets up `ag` or asks how to start/configure/troubleshoot:

1. **Inspect status and configuration guide**:
   Run `ag_status(root="<PROJECT_ROOT>")` or `python -m ag config <PROJECT_ROOT>`.
   Read `onboarding` (`step`, `next_action`, `enrolled`, `reviewer_ready`) and `config_guide` (`global_config_path`, `project_config_path`, `template`, `fields`, `api_key_env`, `api_key_present`).
2. **Zero-pollution enrollment**:
   If `enrolled` is `false`, run `ag_enroll(root="<PROJECT_ROOT>")` (`python -m ag enroll <PROJECT_ROOT>`). This automatically adds `.data/` and `.ag-check/` to `<PROJECT_ROOT>/.git/info/exclude` (never polluting `.gitignore`) and generates an initial `<PROJECT_ROOT>/.data/ticket.md` template if missing.
3. **Guide standard JSON configuration (`critic.json`)**:
   If the user wants independent DS review (`ticket` at start + `switch` at verify) and `reviewer_ready` is `false`, show them the standard JSON format from `config_guide.template` for `<AG_HOME>/critic.json` (or `<AG_HOME>/projects/<PROJECT_KEY>/critic.json`) and instruct them to set the environment variable named in `api_key_env` (e.g., `AG_CRITIC_API_KEY`). **Never ask for, read, or print raw API keys.**
4. **Write high-quality `<PROJECT_ROOT>/.data/ticket.md`**:
   - Under `## 意图`, write a plain-language `做成之后：` statement explaining the observable outcome.
   - Write each `anchor:` with a complete **positive + negative/boundary behavior chain**: state where/what mechanism is built, what happens under normal conditions (`当……时……`), and how edge cases or violations are intercepted/handled (`若……则……`).
   - Under `## 红线`, write 3–5 narrow, task-specific constraints (no generic boilerplate like "write clean code", and do not copy-paste unchanged red lines across consecutive tickets).
5. **Handle `ticket-review-rejected` or `script-prescreen-rejected` in place**:
   If `ag_start` reports `ticket_review.outcome == "rejected"`, inspect `reasons`, `suggestions`, `doubts`, and `script_digest`. Edit `<PROJECT_ROOT>/.data/ticket.md` to resolve the gaps and **re-run `ag_start` directly** (while unconfirmed, `ag_start` re-seals `.data/redlines.copy` and re-reviews in place without requiring `ag_abandon`).

## Opening

1. Read the user's actual words and the project instructions.
2. Identify the endpoint, then work backwards:
   - object: what concrete surface or code path is in play?
   - method: which real mechanism will be used?
   - scope: what is included and what is explicitly excluded?
   - finish: what evidence makes this round complete?
3. Do not ask for permission to proceed. Put reasonable defaults under
   `我替你定的`.
4. Write short anchor lines into `<PROJECT_ROOT>/.data/ticket.md` and the `ag_start` portrait:
   - `anchor: <soft attention with positive + negative/boundary behavior chain>`
   - `anchor!: <hard rule only when it follows from an explicit user/project rule>`
5. A hard anchor is never invented from an AI guess. The AI may propose an
   upgrade, but must label the source.
6. If a blocking unknown remains (endpoint, method, scope, or finish cannot be
   determined), stop and ask one concise question instead of inventing work.

## Mandatory intent-map confirmation

After `ag_start` (once `ticket_review` passes or is unconfigured), stop immediately. Paste the returned `anchor_preview` to the user, give the
absolute `<PROJECT_ROOT>/.data/ticket.md` path (`anchor_preview_path`), and wait. Do not create any worker/subagent or start
implementation until the user explicitly confirms the intent map and
`python -m ag confirm-map <PROJECT_ROOT>` has been run. The AI must never self-invoke `confirm-map`; it
represents the user's approval.

## While working

- Work strictly inside `<WORKTREE>`, never in `<PROJECT_ROOT>`.
- Write one-off verification scripts for this ticket inside `<WORKTREE>/.ag-check/` (discarded upon `ag_finish`; never create standing `tests/`).
- Re-read anchors before file edits and before changing direction.
- Anchors are attention, not a checklist. They may be approached approximately.
- If a suggestion drifts from a soft anchor, continue but disclose the drift.
- If it conflicts with a hard anchor, state the conflict first and ask whether
  the anchor should be revised.
- Never silently rewrite or delete an anchor.
- Do not turn soft anchors into a finish gate.

## Layered intent map

The intent document is canonical `<PROJECT_ROOT>/.data/ticket.md`. `ag_start` refuses without it.

- Put the observable done-state in `fixed` or in portrait lines `固定:` / `做成之后:`.
  `## 意图` is kept as written. Later status, verify, and finish rewrite only `## 现场`.
  To change the locked intent after confirmation, abandon the ticket (`ag_abandon`) and start again.
- Hard anchors are locked rules. They are sealed into `## 红线` and `.data/redlines.copy`
  at start. A hard anchor still comes only from an explicit user or project rule.
- Route anchors are only unsettled attention: soft, discoverable, defaulted,
  or obsolete. They are middle stations, not restated acceptance rules.
- Use verb-bearing declarative sentences of at least 20–25 characters. Name the
  object, the direction, the positive path (`当……时……`), and the negative/boundary guard (`若……则……`).
- Do not collapse an anchor into a bare slogan such as "make it trustworthy";
  a good anchor can be followed without becoming a command list.
- Guards are mandatory rules, passed as `--guard` / MCP `guards`. They render
  in the GUARDS section and never join the START→END path.
- Defaults are negotiable choices, passed as `--default` / MCP `defaults`.
  They render in the DEFAULTS section and are not completion proof.
- Avoid is a separate boundary, not a middle station.

The document the user confirms is `<PROJECT_ROOT>/.data/ticket.md`. Do not keep a second intent map.
Nine or more route anchors should prompt consolidation.

## Canonical freeze

While a task is open, AG freezes tracked files on `<PROJECT_ROOT>`. Windows uses a recoverable ACL deny-write entry for the current user. Other systems use the read-only bit. The read-only bit and the ACL are strong friction against accidental edits. They are not an absolute security boundary. If that checkout is dirty during an open task, `ag_verify` refuses immediately and records `canonical-dirty`.

## Delivery

- Use `ag_start` with the portrait and explicit anchors when available.
- Create workers only with `python -m ag worker-create <PROJECT_ROOT> ...`; use at most 3 workers.
- Pass the anchor preview, the `<PROJECT_ROOT>/.data/ticket.md` path, and anchors to any worker prompt.
- Before completion, run `ag_verify`; do not self-certify.
- Report absolute paths for generated files.
