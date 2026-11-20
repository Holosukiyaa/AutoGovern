---
name: ag-troubleshooting
description: >
  Use when any ag command or MCP tool raises ChainBroken, refuses an
  action, or reports hazards such as canonical-dirty, missing
  the AG project ticket.md, script-prescreen-rejected, ticket-review-rejected,
  intent-map-unconfirmed, canonical freeze/read-only files, switch reject
  or void, missing worker results, or probe red.
---

# `ag-troubleshooting`：常见报错码与排障手册

先用 `python -m ag delivery <PROJECT_ROOT> --task-id <TASK_ID>`（MCP `ag_delivery`）查同票事实，再看 `blockers` 的证据和下一动作。普通建议在 `advisories`；历史拒绝保留原结论，不借全项目 last 成功补齐。`status` 是只读查询，完整体检显式调用 `ag_see`。

| 状态或错误 | 修复动作 |
| --- | --- |
| `task-not-found` / `wrong-task` | 核对票号及报告所属任务；不会回退另一票。 |
| `ticket-review-rejected` | 按具体拒绝修改未确认的票，再次 `start` 原地重审。三维阈值不变，累计票数不加严。 |
| `intent-identity-changed` / `await-user-decision` | 核对同票差异；确认前改票用 `start` 重封存、重审，确认后用 `abandon` 保留候选并重新开票。 |
| `config-error` | 修复当前配置，不能通过默认配置吞掉损坏来源。 |
| `approved-but-frozen` / `thaw-failed` | 已批准仍未就绪，保留批准来源，修复权限或占用后按 `delivery.next_action` 正式恢复；AI 不代确认。 |
| `long-ticket-retired` | 活动旧长票只能用 `abandon` 关闭；旧数据原样保留，不迁移。 |
| `check-digest-mismatch` | 当前票脚本改变，重新 `verify`；检查自动选择本票 `.ag-check/check_*.py`。 |
| `pending-behavior` / `unproven` 探针 | 保留线索，用 `probe calibrate` 提供实际修复前失败、修复后通过的命令观察；无法区分则待查，不当成已证实回归。真实红灯仍阻塞。 |
| `history-corrupt` | `history_issues` 列出坏行的 `path` 与 `line`；读取跳过坏行，`start/verify/finish`、续写、编号写入和 `prune` 拒绝。ag 不自动删除或改写坏行：备份后由用户人工核对并修复或移走该行，再重试。 |
| 探针 `timeout_s` 被拒 / lift 条目 `timed_out=true` | 探针 `timeout_s` 须为 1 到 1800 的整数（默认 30 秒）；`AG_LIFT_CMD` 超过 `AG_LIFT_TIMEOUT`（1 到 1800，默认 300）秒被结束整个进程树，检查命令为何卡住或调大该值。 |
| `history-source-error` / 归档写失败 | 原件保留，修复来源或磁盘后重试 `prune`；索引可重建，不手工删分卷。 |
| `history-close-pending` / `cleanup-pending` | 活动指针保留，排除文件占用后重试原 `finish` 或 `abandon`；已合入的票用 `finish` 恢复清理。 |

确认路径会把检查、授权、解冻和就绪阶段写到 stderr，stdout 保持 JSON。只有 `ready` 代表实际可写；不要因看到“已批准”就开始施工。活动票在 `<AG_HOME>/projects/<key>/draft/ticket.md`，历史事实在 `history/`，旧散档只在核对身份并可靠发布分卷后回收，准备、审计和备份材料保留。

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
  - （注：`.ag-check/` 会由 `ag` 自动写入 `<PROJECT_ROOT>/.git/info/exclude`，不会触发此报错。）
- **[解决办法]**：
  1. 在 `<PROJECT_ROOT>` 下运行 `git status --porcelain` 查看具体是哪些文件脏了。
  2. **若当前没有活动任务（`process: idle`）**：将 `<PROJECT_ROOT>` 下的改动正式 `git commit`、暂存 `git stash`，或清理多余未跟踪文件后再重试。
  3. **若当前已有活动任务（`process: active`）且误改了 `<PROJECT_ROOT>`**：将误改内容移入隔离工作树 `<WORKTREE>`，并将 `<PROJECT_ROOT>` 恢复为干净状态（`git checkout -- .` 或移除多余未跟踪文件），然后重新运行 `ag_verify`。

---

## 2. 文件包校验与基线失败

| 拒绝码 | 处理方式 |
|---|---|
| `ticket-package-missing` | 在项目 ag 家里的 draft/ 填写 ticket.md、spec.json 和 checks/。旧单文件票不再读取。 |
| `ticket-md-invalid` | 补齐四个非空段落，拍板项可写“无”。 |
| `spec-invalid` | 按错误给出的字段路径修复 spec；模板必须先填写 origin.user_words。 |
| `result-uncovered` | 给报出的 result 补一条 target 检查。 |
| `invalid-continuation` | spec.continuation_of 只能引用已关闭且本人确认的前票，不传递授权。 |
| `baseline-target-green` | 指出的 target 在基线上已通过，不能证明新结果；重写真实结果检查。 |
| `baseline-guard-red` | 指出的 guard 在基线上失败，先核对原有行为和检查，不能放宽检查。 |
| `sealed-check-changed` | 封存区文件被修改、删除或新增；恢复封存原文后重新验货，不改 seal 来掩盖。 |
| `seal-invalid` | seal.json 损坏或缺少字段；status 显示风险，verify/finish 拒绝，abandon 仍可关闭。 |
| `legacy-ticket-format` | 旧活动票没有封存包，只能 abandon 关闭后用 draft/ 重新开票。 |

## 4. `intent-map-unconfirmed` / 工作树 `<WORKTREE>` 文件只读无法写入

- **现象**：工作树不可写，或 verify/finish 报缺少有效授权。
- **核对原因**：读取同票 `delivery`，区分尚未本人确认、当前审票拒绝/不可用、票面变化，以及解冻失败。
- **本人确认**：展示本票完整 `anchor_preview`，由用户本人执行 `python -m ag confirm-map <PROJECT_ROOT>`。AI 不得代调。
- **已批准但解冻失败**：保留批准来源与失败事实，修复权限或占用后正式重试；不重复业务授权，不手改 ACL/状态绕过门禁。只有实际 `ready` 才可创建 Worker 或施工。

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
    - **原因**：`switch` 终审发现代码未实现票面意图、触碰红线、存在边界漏洞，或本票自检未检验核心逻辑。自动种入的问题指针记录在 `probes_planted` 中，初始为待核查线索。
    - **办法**：阅读 `verify.switch.summary` 与 `items` 的精确证据，修复代码并完善 `.ag-check/`。待核查指针需用修复前后行为对照校准；已验证探针的真实红灯仍须修复，再运行 `ag_verify`。
  - **子情况 6.3：`outcome: "unavailable"`（审核服务不可用）**
    - 查看 `verify.switch.reason`：
      - `not-configured`：尚未配置独立审核席位（未配置时默认不拦截 `finish`；若需启用，运行 `python -m ag config <PROJECT_ROOT>` 查看配置指南并填写 `config.json` 的 `critic` 段）。
      - `missing_api_key:<ENV_NAME>`：已在 `config.json` 启用审核，但当前环境中未找到 `<ENV_NAME>` 环境变量。请设置对应环境变量后重跑 `ag_verify`（详见 [`skills/ag-config/SKILL.md`](../ag-config/SKILL.md)）。
      - `same_family:<FAMILY>`：`config.json` 的 `critic` 段中的审核 `model` 与施工 `worker_model` 属于同一模型家族。请更换异构审核模型，或在 `critic` 段中显式设置 `"allow_same_family": true`。
      - `void:...`（如网络超时、HTTP 报错或返回非 JSON）：远程大模型接口调用异常。因已启用审核席位，为遵循 fail-closed 原则，`void` 状态的 `switch` 会拒绝 `finish`。请检查网络、`endpoint` 地址或适当调大 `critic` 段中的 `"timeout"`（单次审核调用的总耗时上限，如 `120`），然后重跑 `ag_verify`。

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


## 单票与旧数据

每张票独立审票，由用户本人执行 `confirm-map`，实际解冻并返回 `ready` 后才可施工。`continuation_of` 仅携带前票共同目标、贡献与未完成项作参考，不传递授权。

T4 之前，修改已确认的票须先 `abandon`（候选保存在 `refs/ag/abandoned/<task_id>`），再重新开票；确认前改票可用 `start` 原地重新封存、审票。

遇到 `long-ticket-retired` 时用 `abandon` 关闭活动票。旧长票数据原样留在 `<AG_HOME>`，不迁移；新代码不读取、不改写、不删除旧 `long/`、`long-goals.sqlite3` 和历史记录。归档票查询只提供降级视图，不授予权限。

## 票包与确认前重审

票据文件包放在 `<AG_HOME>/projects/<key>/draft/`：`ticket.md` 给人看，`spec.json` 给机器看，`checks/` 放开票前写好的 Python 检查及辅助文件。enroll 生成起步模板；`origin.user_words` 默认为空，必须按用户原话填写后才可 start。

`ticket.md` 必须有四个非空段落：`## 要做成什么`、`## 怎样算做成`、`## 不做什么`、`## 需要你拍板的事`，最后一段可写“无”。不再把机器结果或检查藏在人话标记行中。

start 校验、把 draft 逐字节封存到 `tickets/<task_id>/`，在尚未解冻的 source_head 工地中运行封存检查，cwd 为工地，每条用 Python 执行且限时 300 秒。target 基线必须失败，guard 必须通过，再把完整人话、spec、检查源码和基线交给独立 ticket 席位。seal.json 原子写入，记录全部文件摘要、身份、基线和审核回执。

每张票仍须用户本人 confirm-map，AI 不得代调；实际解冻并返回 ready 后才可施工。verify 运行封存检查、工地 `.ag-check/check_*.py` 追加检查及项目登记命令，并调用 switch；finish 复核 seal、候选和审核后快进合入。封存 ticket.md 不回写现场段，现场由 status/delivery 展示。

确认前修改 draft 再 start，在同一 task_id 重封存、重跑基线并重新审票；没有改动只恢复现场。确认后改票属于 T4b，本版先 abandon（候选保留在 `refs/ag/abandoned/<task_id>`）再重新开票。不要直接改封存区。
