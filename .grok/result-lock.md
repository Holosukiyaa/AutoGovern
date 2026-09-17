## Result lock
Task: ag v1 is a short MCP delivery loop — worktree, enrolled tests, hook, ff-only — no GUI
Status: LOCKED

### Done looks like
An agent enters only through ag MCP (CLI twins exist for the same verbs). After enroll, the canonical checkout is not a work site: start returns a worktree path; `git commit` on canonical exits non-zero; finish fast-forwards only when the last verify tree digest still matches. Verify runs the enrolled test command. Finish JSON always splits process vs product; missing tests → product stays undeclared even if process completed.

### Surfaces
#### MCP loop tools [Interface]
(STATED) Main entry is MCP. (INFERRED) Tools: `ag_enroll`, `ag_status`, `ag_start`, `ag_verify`, `ag_finish`, `ag_abandon`. `root` is required. Start returns `worktree.path`. Verify/finish return `process` and `product` (`passed` | `failed` | `undeclared` | `pending`). Error is `isError` with a reason, not a green payload.
- Encountered as: MCP `tools/call`
- Empty / error / denied / success: not enrolled → error; canonical dirty at start/finish → error; digest mismatch at finish → error; tests fail at verify → `process=active`, `product=failed`
- Unchanged nearby: no probe-queue tools

#### CLI twins [Command]
(INFERRED) `ag enroll|status|start|verify|finish|abandon|unenroll <root>` print the same JSON. `ag enroll <root> --test <argv...>` registers the product command. `ag hook` is what the Git hook execs.
- Example: `ag start C:\proj` → JSON with `worktree`
- Empty / error / denied / success: exit 1 + stderr reason on ChainBroken

#### Git hook [Command]
(STATED) Delivery gate is Git, not GUI. (INFERRED) enroll sets `core.hooksPath` to a generated `pre-commit` that runs `python -m ag hook`. Canonical commit refused (even with AG_DELIVER). Worktree commit only with AG_DELIVER=1 from finish. Previous hooksPath is saved and run after a worktree deliver. Enroll canary: empty canonical commit must fail. Unenroll restores the previous hooksPath.
- Example: `git -C canonical commit` → non-zero, stderr contains `canonical`
- Unchanged nearby: history and remotes stay in the project's `.git`

#### Status honesty [Artifact]
(STATED) process complete ≠ product passed.
- Contents: `hook_ok`, `canonical_dirty`, `hazards`, `process`, `product`, optional `portrait`
- Example: no `--test` at enroll → every later payload `product: "undeclared"`
- Absent: knowledge cards, census, regulator, flatten, GUI, coverage percent

### Out of result
- GUI / tray / file tree
- Knowledge cards, census, DeepSeek, AGF coordinates, flatten/glue city
- Rebase/refresh when canonical moved (finish refuses)
- Refusing all untracked files at finish (would block new product files)
- ag special-casing itself

### Inferences
- Worktrees live under `%AG_HOME%` or `~/.ag/worktrees/<key>/`, not inside the project
- Identity is `os.path.realpath` so a junction is one project
- Tree digest is `git add -A` + `git write-tree` in the worktree
- One open task per project; second start returns the existing worktree
- Probe queue remains; verify does not run it
