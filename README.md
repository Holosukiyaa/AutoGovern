# ag

Four lanes that must not mix: **ship (交货)** · **heal (治病)** · **lift (抬正确率)** · **see (看见)**.

Only ship may set `product` or refuse `finish`. heal / lift / see are advice or observation.

MCP delivery loop. Canonical checkout is not a work site. While a task is open, tracked canonical files are read-only.

```
ag_status → ag_start → write only in worktree → ag_verify → ag_finish
```

Do **not** store long-lived tests in this repo. Worker checks belong in worktree `.ag-check/` (gitignored, discarded at finish). Old `tests/` is a standing answer key for the next AI; it is forbidden here.

`ag_verify` runs an enrolled command only if one was set (other products may enroll a tiny smoke). This repo enrolls **no** test command: `product` stays `undeclared` unless a probe is red. Then path-hit probes, then one read-only critic. Critic is a layer before the switch: `rejected` does not refuse this ticket's finish. Probe red still refuses finish.

```
ag enroll <repo>
ag mcp
```

Critic config lives in `~/.ag/projects/<key>/critic.json`. Audit: sqlite `ag.sqlite`. `ag critic-log` / `ag-gui.bat` (pick an enrolled repo).
