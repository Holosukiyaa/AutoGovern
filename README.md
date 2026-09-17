# ag

Four lanes that must not mix: **ship (交货)** · **heal (治病)** · **lift (抬正确率)** · **see (看见)**.

Only ship may set `product` or refuse `finish`. heal / lift have no tools yet. `ag plug list|on|off <repo> lift-4` toggles a pluggable strategy; ship core cannot be unplugged. `ag lift` / `ag heal` / `ag see` run the other lanes as advice and findings — they cannot refuse finish. `ag usage` counts help/block by lane-seq. `ag gui [repo]` writes a read-only HTML dashboard. Double-click `ag-gui.bat`.

MCP delivery loop. Canonical checkout is not a work site.

```
ag_status → ag_start → write only in worktree → ag_verify → ag_finish
```

`ag_verify` runs the test command registered at enroll. Process complete is not product passed. No test command → `product` stays `undeclared`. Git hook refuses `git commit` on canonical. `ag unenroll` restores the previous hooksPath. Worktree commits only go through `ag_finish`.

```
ag enroll <repo> --test python -m unittest
ag mcp
```
