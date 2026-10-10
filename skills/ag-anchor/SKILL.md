---
name: ag-anchor
description: >
  Use for any ag-governed delivery task, especially before ag_start and when
  the user's one-sentence request hides a route. Extract user-facing intent
  anchors, keep them as attention rather than a plan, persist them through ag,
  and disclose deviations. Also use when the user says 锚点, 意图锚点, route,
  or when a later suggestion conflicts with an existing anchor. This skill does
  not replace ag; delivery still goes through ag_start → ag_verify → ag_finish.
---

# ag intent anchors

Intent anchors make the user's hidden route explicit without turning it into a
step plan. `ag` remembers them in task state; the AI must read them at the
start, while working, and before verification.

## Opening

1. Read the user's actual words and the project instructions.
2. Identify the endpoint, then work backwards:
   - object: what concrete surface or code path is in play?
   - method: which real mechanism will be used?
   - scope: what is included and what is explicitly excluded?
   - finish: what evidence makes this round complete?
3. Do not ask for permission to proceed. Put reasonable defaults under
   `我替你定的`.
4. Write short anchor lines into the `ag_start` portrait:
   - `anchor: <soft attention>`
   - `anchor!: <hard rule only when it follows from an explicit user/project rule>`
5. A hard anchor is never invented from an AI guess. The AI may propose an
   upgrade, but must label the source.
6. If a blocking unknown remains (endpoint, method, scope, or finish cannot be
   determined), stop and ask one concise question instead of inventing work.

## Mandatory intent-map confirmation

After `ag_start`, stop immediately. Paste the returned `anchor_preview` to the user, give the
absolute Unicode map path, and wait. Do not create any worker/subagent or start
implementation until the user explicitly confirms the intent map and
`confirm-map` has been run. The AI must never self-invoke `confirm-map`; it
represents the user's approval.

## While working

- Re-read anchors before file edits and before changing direction.
- Anchors are attention, not a checklist. They may be approached approximately.
- If a suggestion drifts from a soft anchor, continue but disclose the drift.
- If it conflicts with a hard anchor, state the conflict first and ask whether
  the anchor should be revised.
- Never silently rewrite or delete an anchor.
- Do not turn soft anchors into a finish gate.

## Layered intent map

The map has a locked block above the route.

- Put the observable done-state in `fixed` or in portrait lines `固定:` / `做成之后:`.
  That text is snapshotted at `ag_start`. Later `ag_status` redraws the route
  but does not replace those lines. To change them, abandon the ticket and
  start again after the user rejects the map.
- Hard anchors are locked rules. They render inside the fixed block, not as
  route stations. A hard anchor still comes only from an explicit user or
  project rule.
- Route anchors are only unsettled attention: soft, discoverable, defaulted,
  or obsolete. They are middle stations, not restated acceptance rules.
- Use verb-bearing declarative sentences of at least 20 characters. Name the
  object, the direction, and the reason this station moves toward the endpoint.
- Do not collapse an anchor into a bare slogan such as "make it trustworthy";
  a good anchor can be followed without becoming a command list.
- Guards are mandatory rules, passed as `--guard` / MCP `guards`. They render
  in the GUARDS section and never join the START→END path.
- Defaults are negotiable choices, passed as `--default` / MCP `defaults`.
  They render in the DEFAULTS section and are not completion proof.
- Avoid is a separate boundary, not a middle station.

The map shows the route, endpoint, discoverable unknowns, blocking unknowns,
guards, defaults, and avoid zone. The map is Unicode text. Nine or more
route anchors should prompt consolidation.

## Canonical freeze

While a task is open, AG freezes tracked files on the canonical checkout. Windows uses a recoverable ACL deny-write entry for the current user. Other systems use the read-only bit. The read-only bit and the ACL are strong friction against accidental edits. They are not an absolute security boundary. If that checkout is dirty during an open task, `ag_verify` refuses immediately and records `canonical-dirty`.

## Delivery

- Use `ag_start` with the portrait and explicit anchors when available.
- Create workers only with `ag worker-create`; use at most 3 workers.
- Pass the anchor preview, Unicode map path, and anchors to any worker prompt.
- Before completion, run `ag_verify`; do not self-certify.
- Report absolute paths for generated files.
