# ag

Four lanes that must not mix: **ship (交货)** · **heal (治病)** · **lift (抬正确率)** · **see (看见)**.

Only ship may set `product` or refuse `finish`. heal / lift / see are advice or observation.

MCP delivery loop. Canonical checkout is not a work site. While a task is open, tracked files on canonical are read-only.

```
ag_status → ag_start → write only in worktree → ag_verify → ag_finish
```

`ag_verify` runs the enrolled test command, then path-hit out-of-tree probes, then one read-only critic (if configured). Process complete is not product passed. No test command → `product` stays `undeclared` unless a probe is red or the critic refuses.

Finish also refuses when:

- this ticket's probes are red
- critic outcome is `rejected`
- critic is configured and `unavailable` for a reason other than `not-configured`

```
ag enroll <repo> --test python -m unittest
ag mcp
```

Critic config lives in `~/.ag/projects/<key>/critic.json` (not in the git tree). Audit log: sqlite `ag.sqlite` table `critic_event` (jsonl is a backup). `ag critic-log` reads the database. `ag gui <repo>` writes HTML of critic_event rows and current probes (exam_fragment only). Critic `rejected` with `path:line` auto-plants a must_exclude probe; heal does not. Default `ag probe list` hides observation/evidence (`--full` for a person).

`ag plug list|on|off <repo> lift-4` toggles a pluggable strategy; ship core cannot be unplugged. `ag usage` counts help/block by lane-seq.
