---
name: ag-troubleshooting
description: >
  Use when any ag command or MCP tool raises ChainBroken, refuses an
  action, or reports hazards such as canonical-dirty, missing
  <AG_HOME>/projects/<key>/ticket.md, script-prescreen-rejected, ticket-review-rejected,
  intent-map-unconfirmed, canonical freeze/read-only files, switch reject
  or void, missing worker results, or probe red.
---

# `ag-troubleshooting`：常见报错码与排障手册

当你在执行 `ag_enroll`、`ag_start`、`confirm-map`、`ag_verify` 或 `ag_finish` 遇到报错或拦截时，可按本技能包对照 **`[现象/报错]` → `[原因]` → `[解决办法]`** 快速排障。

> 💡 **快速自检提示**：绝大多数状态下，直接运行 `<PYTHON_EXECUTABLE> -m ag status <PROJECT_ROOT>`（或 `python -m ag status <PROJECT_ROOT>`）并查看返回 JSON 中的 `onboarding`、`hazards` 与 `last_error`，就能直接看到针对当前卡点的中文修复路牌。

- **返回项目总入口**：[`AGENTS.md`](../../AGENTS.md)
- **查看 6 步使用流程**：[`skills/ag-guide/SKILL.md`](../ag-guide/SKILL.md)
- **意图锚点与写票规范**：[`skills/ag-anchor/SKILL.md`](../ag-anchor/SKILL.md)
- **查看配置文件格式**：[`skills/ag-config/SKILL.md`](../ag-config/SKILL.md)

统一路径占位符约定：`<PROJECT_ROOT>`（主仓根目录）、`<AG_REPO_ROOT>`（`ag` 源码根目录）、`<WORKTREE>`（隔离工作树目录）、`<AG_HOME>`（默认 `~/.ag`）、`<PYTHON_EXECUTABLE>`（如 `python`）。

---

## 1. `canonical checkout is dirty` / `canonical-dirty`

- **[现象/报错]**：
  - 执行 `ag_enroll`、`ag_start`、`ag_verify` 或 `ag_finish` 时报错：`canonical checkout is dirty (<PROJECT_ROOT>)`，或 `ag_verify` 返回 `reason: "canonical-dirty"`。
- **[原因]**：
  - `ag` 要求主仓检出区（`<PROJECT_ROOT>`）在开工前、施工期间和合入时必须保持 Git 状态完全干净。
  - 若 `<PROJECT_ROOT>` 下有未提交的跟踪文件修改，或存在未被忽略的未跟踪杂物文件，护栏会立即熔断拒绝，防止脏代码混入或破坏 `--ff-only` 快进合入。
  - （注：`.data/` 与 `.ag-check/` 会由 `ag` 自动写入 `<PROJECT_ROOT>/.git/info/exclude`，不会触发此报错。）
- **[解决办法]**：
  1. 在 `<PROJECT_ROOT>` 下运行 `git status --porcelain` 查看具体是哪些文件脏了。
  2. **若当前没有活动任务（`process: idle`）**：将 `<PROJECT_ROOT>` 下的改动正式 `git commit`、暂存 `git stash`，或清理多余未跟踪文件后再重试。
  3. **若当前已有活动任务（`process: active`）且误改了 `<PROJECT_ROOT>`**：将误改内容移入隔离工作树 `<WORKTREE>`，并将 `<PROJECT_ROOT>` 恢复为干净状态（`git checkout -- .` 或移除多余未跟踪文件），然后重新运行 `ag_verify`。

---

## 2. 找不到票：`ag_start needs a ticket`

- **[现象/报错]**：
  - 调用 `ag_start` 时报错：`ag_start needs a ticket; missing <AG_HOME>/projects/<key>/ticket.md`（附中文原因与下一步），或提示缺少锚点/完成态描述。
- **[原因]**：
  - `<AG_HOME>/projects/<key>/ticket.md` 不存在，或者里面只有空模板，没有填写有效的 `做成之后：`（或 `固定:`）完成态意图与至少一条 `anchor:` 锚点。
- **[解决办法]**：
  1. 若尚未登记仓库，先运行 `python -m ag enroll <PROJECT_ROOT>`（会自动生成 `<AG_HOME>/projects/<key>/ticket.md` 初始模板）。
  2. 打开 `<AG_HOME>/projects/<key>/ticket.md`，在 `## 意图` 下填写 `做成之后：...` 及至少一条完整的 `anchor: ...`，在 `## 红线` 下填写聚焦禁令（写法详见 [`skills/ag-anchor/SKILL.md`](../ag-anchor/SKILL.md) 与 [`skills/ag-guide/SKILL.md`](../ag-guide/SKILL.md) 第 2 步），保存后重新运行 `ag_start`。

---

## 3. `script-prescreen-rejected` / `ticket-review-rejected`（开票审票未通过）

- **[现象/报错]**：
  - `ag_start` 返回 `ticket_review.outcome: "rejected"`，且执行 `confirm-map` 时被拦截报错：`intent-map-ticket-rejected: ticket review rejected ...`。
- **[原因]**：
  - **情况 A（`script-prescreen-rejected` 本地 0-Token 预筛拦截）**：
    - `## 意图` 描述太短（少于 30 字），没有用大白话讲清楚业务结果；
    - `anchor:` 少于 25 字，或只写了正向动作，缺少“当……时……，若……则……”的正反向/边界闭环（`anchor_missing_negative_or_boundary`）；
    - `## 红线` 写了“代码要规范”“不能有 bug”等空泛套话，或者与上一张票红线高度雷同照抄。
  - **情况 B（`ticket-review-rejected` 独立 `ticket` 席位打回）**：
    - 独立审核模型对 `goal_clarity`（目标清晰度）、`anchor_chain`（锚点链路完整性）、`redline_focus`（红线聚焦度）任一维度打分 `< 7`，或者提出了需要澄清的疑惑（`doubts` 非空）。
- **[解决办法]**：
  1. 查看 `ag_start` 或 `ag_status` 返回的 `ticket_review.reasons`、`ticket_review.suggestions`、`ticket_review.doubts` 以及 `ticket_review.script_digest.hard_failures`。
  2. **无需执行 `ag_abandon`！** 在任务尚未 `confirm-map` 前，直接编辑 `<AG_HOME>/projects/<key>/ticket.md`，补齐大白话业务目标、正反向行为链路锚点和聚焦红线，解答 `doubts` 中的疑问。
  3. 直接再次运行 `ag_start`：系统会自动用新票据原地更新封存红线（`<AG_HOME>/projects/<key>/redlines.copy`）并开启新一轮无状态 `ticket` 审票，通过后再由用户执行 `confirm-map`。

---

## 4. `intent-map-unconfirmed` / 工作树 `<WORKTREE>` 文件只读无法写入

- **[现象/报错]**：
  - AI 尝试在 `<WORKTREE>` 修改文件时提示 Permission denied / 文件只读，或运行 `ag_verify` / `ag_finish` 报错 `intent-map-unconfirmed: show anchor_preview to the user and run ag confirm-map first`。
- **[原因]**：
  - `ag_start` 创建工作树后，默认会将 `<WORKTREE>` 也设为只读冻结状态，强制要求 AI 先把 `<AG_HOME>/projects/<key>/ticket.md`（`anchor_preview`）展示给用户看，防止 AI 不经用户同意就直接闷头改代码。
- **[解决办法]**：
  1. AI 将 `anchor_preview` 展示给用户，等待用户明确回复确认。
  2. 由用户在终端执行解冻命令：
     ```powershell
     python -m ag confirm-map <PROJECT_ROOT>
     ```
  3. 命令执行成功后，`<WORKTREE>` 自动解除只读限制，即可正常编辑代码。

---

## 5. 主仓 `<PROJECT_ROOT>` 文件只读 / 权限被锁（Canonical Freeze）

- **[现象/报错]**：
  - 在 `<PROJECT_ROOT>` 下无法保存文件，或者任务异常中断后发现主仓文件带有只读属性 / Windows ACL 写拒绝锁。
- **[原因]**：
  - 这是 `ag` 的 **主仓冻结（Canonical Freeze）** 保护机制：只要存在 `process: active` 的进行中任务，`<PROJECT_ROOT>` 下的受跟踪文件就会被锁定为只读，强制所有代码修改只能在 `<WORKTREE>` 中进行。
- **[解决办法]**：
  - **若任务仍在进行中**：不要强行解锁主仓，请切换到 `ag_status.worktree`（即 `<WORKTREE>`）目录下修改代码。
  - **若任务已完成或打算放弃，想恢复主仓正常读写**：
    - 正常交卷合入：运行 `python -m ag finish <PROJECT_ROOT>`，合入后主仓自动解冻。
    - 放弃当前任务立即解冻：运行 `python -m ag abandon <PROJECT_ROOT>`，工作树会被清理，主仓所有文件的只读位与 Windows ACL 会立即自动恢复正常。

---

## 6. `switch` 拒单（`rejected` / `script-syntax-error`）或返回 `unavailable`

- **[现象/报错]**：
  - 运行 `ag_verify` 后，`verify.switch.outcome`（及 `verify.critic.outcome`）显示为 `rejected` 或 `unavailable`，导致 `ag_finish` 被拒绝。
- **[原因与对应解决办法]**：
  - **子情况 6.1：`reason: "script-syntax-error"`**
    - **原因**：`<WORKTREE>` 中修改的 Python 文件存在语法错误（`ast.parse` 编译失败），被本地 0-Token 预筛直接熔断短路，未调用远程大模型。
    - **办法**：查看 `verify.switch.findings` 中指出的具体 `file` 和 `line`，在 `<WORKTREE>` 中修复语法错误后重跑 `ag_verify`。
  - **子情况 6.2：`outcome: "rejected"`（代码终审不通过）**
    - **原因**：`switch` 终审发现代码未实现 `<AG_HOME>/projects/<key>/ticket.md` 的意图、触碰了 `## 红线`、存在未处理的边界漏洞，或工作树里的一次性自检脚本没有真正检验核心逻辑。同时，`switch` 会根据发现的问题自动种入回归探针（记录在 `planted_probes` 中）。
    - **办法**：仔细阅读 `verify.switch.summary` 与 `verify.switch.findings`（含精确 `file`、`line` 和 `message`），在 `<WORKTREE>` 中修复代码并完善 `.ag-check/` 脚本，确保新种入的探针也能跑绿，然后重新运行 `ag_verify`。
  - **子情况 6.3：`outcome: "unavailable"`（审核服务不可用）**
    - 查看 `verify.switch.reason`：
      - `not-configured`：尚未配置独立审核席位（未配置时默认不拦截 `finish`；若需启用，运行 `python -m ag config <PROJECT_ROOT>` 查看配置指南并填写 `critic.json`）。
      - `missing_api_key:<ENV_NAME>`：已启用 `critic.json`，但当前环境中未找到 `<ENV_NAME>` 环境变量。请设置对应环境变量后重跑 `ag_verify`（详见 [`skills/ag-config/SKILL.md`](../ag-config/SKILL.md)）。
      - `same_family:<FAMILY>`：`critic.json` 中的审核 `model` 与施工 `worker_model` 属于同一模型家族。请更换异构审核模型，或在 `critic.json` 中显式设置 `"allow_same_family": true`。
      - `void:...`（如网络超时、HTTP 报错或返回非 JSON）：远程大模型接口调用异常。因已启用审核席位，为遵循 fail-closed 原则，`void` 状态的 `switch` 会拒绝 `finish`。请检查网络、`endpoint` 地址或适当调大 `critic.json` 中的 `"timeout"`（如 `120`），然后重跑 `ag_verify`。

---

## 7. `missing worker results`（Worker 档案未生成 `result.json`）

- **[现象/报错]**：
  - `ag_verify` 返回 `ok: false`，且 `verify.missing_worker_results` 列出一个或多个 `<WORKER_ID>`。
- **[原因]**：
  - 当前任务通过 `ag worker-create` 创建了子代理任务档案，但对应 Worker 尚未在 `<WORKTREE>.artifacts/workers/<WORKER_ID>/result.json` 下写入合规的 `ag.worker.result.v1` 结果文件，或文件内容不符合 Schema。
- **[解决办法]**：
  1. 让对应的子代理完成工作并写入 `result.json`（需包含 `"schema": "ag.worker.result.v1"`、`task_id`、`status`、`summary`、`changed_files`、`anchor_receipt`、`evidence`、`open_questions`）。
  2. 运行 `python -m ag worker-read <PROJECT_ROOT> <WORKER_ID>` 验证回执格式无误后，重新运行 `ag_verify`。

---

## 8. `probe red`（历史回归探针报警）

- **[现象/报错]**：
  - `ag_verify` 返回 `verify.probes.status: "red"`，拒绝合入。
- **[原因]**：
  - 本次修改命中的文件路径触发了过往任务或上一轮 `switch` 拒单时种下的回归探针（`probe`），且代码触发了探针所防范的回归特征（如删掉了必须保留的关键符号或再次引入了违规模式）。
- **[解决办法]**：
  1. 查看 `ag_verify` 返回的 `verify.probes.results`（或运行 `python -m ag probe-list <PROJECT_ROOT>` / `python -m ag probe-run <PROJECT_ROOT>`），定位报错的 `probe_id`、`path` 与 `reason`。
  2. 在 `<WORKTREE>` 中修复破坏历史契约或违规的代码，使探针重新变绿（`green`），然后重跑 `ag_verify`。

---

## 9. `tree digest mismatch` / 修改代码后直接运行 `ag_finish` 被拒

- **[现象/报错]**：
  - 运行 `ag_finish` 时报错：`worktree changed after ag_verify; run ag_verify again`（或 `tree digest mismatch`）。
- **[原因]**：
  - `ag_verify` 通过时会记录当时 `<WORKTREE>` 的文件树哈希指纹（`verified_tree`）。如果在 `ag_verify` 之后又修改、新增或删除了 `<WORKTREE>` 中的任何受跟踪文件或未跟踪文件，指纹就会失效，防止“验完货再偷偷塞私货”。
- **[解决办法]**：
  - 在 `<WORKTREE>` 保持最终状态不变的前提下，重新运行一次 `ag_verify`，待通过后立即执行 `ag_finish`。

---

## 10. 自检写不下去 / 只能靠造假桩才能测

- **[现象/报错]**：
  - 写 `.ag-check/` 自检时发现：本可以走真实入口（如真实 `session.create`、真实服务调用）验证，却因为真实入口走不通，只能造假桩或手塞假对象才能让自检跑起来。
- **[原因]**：
  - 这多半是**上游真实入口本身坏了**（如注册表缺参数、入口契约与服务层不一致），造假桩是在给这个断点打掩护，断点会埋到后续票才爆。
  - 注意区分：**合理的桩**只有「真外部依赖边界」（如 AI 对话这类本就没真件可连的外部边界）；**警报的桩**是「本可走真件却走不通」。
- **[解决办法]**：
  - 把这当作停止信号，**不要造假蒙混过关**。停下来找用户拍板，说明走不通的真实入口在哪、为什么只能造假；或被 `switch` 终审拦下后回来面对这个断点。
  - 详细处置规范见 `skills/ag-anchor/SKILL.md` 第四节「自检走不通真实入口的处置」。
