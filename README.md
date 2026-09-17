# ag

Four lanes that must not mix: **ship (交货)** · **heal (治病)** · **lift (抬正确率)** · **see (看见)**.

Only ship may set `product` or refuse `finish`. heal / lift have no tools yet. `ag usage` (see) counts help/block per ship item; it is not green. `ag gui [repo]` writes a read-only HTML dashboard and opens it — display only. Double-click `ag-gui.bat` (or drop a repo folder on it).

MCP delivery loop. Canonical checkout is not a work site.

```
ag_status → ag_start → write only in worktree → ag_verify → ag_finish
```

`ag_verify` runs the test command registered at enroll. Process complete is not product passed. No test command → `product` stays `undeclared`. Git hook refuses `git commit` on canonical. `ag unenroll` restores the previous hooksPath. Worktree commits only go through `ag_finish`.

```
ag enroll <repo> --test python -m unittest
ag mcp
```
