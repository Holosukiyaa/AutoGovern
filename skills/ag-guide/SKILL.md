---
name: ag-guide
description: >
  Use when a user or AI asks what ag is, how the ag delivery loop works,
  or how to use ag step by step from enrollment to finish. Covers core
  concepts (ship / lift / see lanes, canonical freeze, worktree isolation,
  one-front-one-back review) and the complete 6-step workflow.
---

# `ag-guide`：这个项目是干什么的？怎么一步步使用？

本技能包用大白话讲清楚 `ag` 解决什么问题、核心设计原理是什么，以及从零开始走完一张交付票的完整 6 步工作流。

## 恢复与连续交付

恢复或交接先运行 `python -m ag delivery <PROJECT_ROOT> --task-id <TASK_ID>`，或调用 `ag_delivery`。活动票和归档票使用相同查询；不存在的票返回 `task-not-found`，不会退回其他票。`goal`、本票贡献、`progress.verified`、`remaining`、阻塞、建议及下一动作附带事实来源；开始或验证失败不会算完成。

完整功能可在一票内分阶段完成，合理换路线可用 `ag route <PROJECT_ROOT> --reason "原因"` 记录；减少承诺或触碰硬边界加 `--requires-decision` 等待用户决定。真正独立交付才用 `start --continuation-of <TASK_ID> --contribution "贡献"`。`status` 只读，完整诊断通过 `ag_see` 显式执行，安装修复通过 `enroll/config`。

确认命令由用户亲自执行，AI 不得代调。阶段写到 stderr，只有实际解冻后才返回 `ready`；`approved-but-frozen`、`thaw-failed` 仍不可施工，修复权限后用户可重试原票确认。交卷时自动选择本工作树 `.ag-check/check_*.py`，不会沿用上一票的脚本名；项目常规检查照常运行。`critic` 兼容字段指向同一 `switch` 报告时只计一次审核。

新事实存入按时间和容量分卷的 JSONL 历史，不逐票增加散档。`ag prune` 先刷新、回读校验并原子发布历史，随后回收已结束且身份明确的旧件；活动票、准备资料、审计资料和用户备份保留。索引可重建，旧格式仍能读；写失败保留来源并明确报错。

- **返回项目总入口**：[`AGENTS.md`](../../AGENTS.md)
- **意图锚点与写票规范**：[`skills/ag-anchor/SKILL.md`](../ag-anchor/SKILL.md)
- **配置独立审核与 MCP 挂载**：[`skills/ag-config/SKILL.md`](../ag-config/SKILL.md)
- **遇到报错查排障手册**：[`skills/ag-troubleshooting/SKILL.md`](../ag-troubleshooting/SKILL.md)

---

## 一、为什么需要 `ag`？（Vibe Coding 的四大翻车现场）

让 AI 写代码很快，但工程交付时经常遇到以下四个致命问题：

| 常见翻车现场 | 没有 `ag` 时的后果 | `ag` 的物理护栏解法 |
| :--- | :--- | :--- |
| **1. 主仓直接改烂** | AI 在主工作区改了一半报错，未提交脏文件混在一起，回滚都找不到干净基线。 | **主仓冻结 + `<WORKTREE>` 隔离施工**：开工即把 `<PROJECT_ROOT>` 设为只读冻结，所有代码只能在独立工作树 `<WORKTREE>` 中修改，验收合格才 `--ff-only` 合入。 |
| **2. 需求理解跑偏 & 偷删底线** | 用户说一句话，AI 脑补出一套复杂架构，改着改着把原有的安全/兼容红线忘得一干二净。 | **启动票锚点 + 红线封存 + 用户确认解冻**：开工前必须把目标、正反向 `anchor:` 和 `## 红线` 写进 `<AG_HOME>/projects/<key>/ticket.md`，封存到 `<AG_HOME>/projects/<key>/redlines.copy`，经 `ticket` 席位审票且用户执行 `confirm-map` 后才解冻工作树。 |
| **3. 写假测试“自己考自己”** | 仓库里留着常驻 `tests/`，AI 为了让测试变绿直接改测试断言或写 `assert True` 糊弄交差。 | **禁止常驻 `tests/` + `.ag-check/` 一次性自检**：本仓不留常驻测试答案库。每张票在 `<WORKTREE>/.ag-check/` 现场写针对本票真实验收逻辑的自检脚本，合入时随 `<WORKTREE>` 自动销毁。 |
| **4. 审校 Token 爆炸或走过场** | 每次检查全量喂大文件耗尽 Token，或者审核照抄旧结论。 | **0-Token 预筛 + 一前一后无状态审核**：裁剪源码窗口，每票独立复述并引用当前证据；累计票数不提高严审等级，阈值与拒绝规则一致。 |

---

## 二、三条正交轨道：`ship` · `lift` · `see`

`ag` 将所有治理动作严格划分为三条不混用的轨道：

1. **`ship`（交货闸）**：唯一有权决定 `product` 状态、唯一有权拒绝 `ag_finish` 合入的硬门禁。包含：主仓干净检查、工作树隔离、意图图确认（`confirm-map`）、Worker 结果完整性、历史回归探针（`probes`）、以及已配置的 `switch` 终审。
2. **`lift`（抬正确率）**：给 AI 与开发者的注意力护栏与过程建议（如 `lift-12` 锚点注意力、`lift-15` 红线脱落提醒、`lift-16` 静默吞异常扫描、`lift-18` 连续票防偷懒检测）。**永远只给建议，不直接拦 `finish`**。
3. **`see`（客观透视）**：纯客观观测台账（如 `see-10/11` CSS 重复选择器与归属、`see-12` 逆向依赖扫描、`see-14` 历史票据统计、`see-15` 审校 Token 节省台账）。**只提供事实，不作主观拦截**。

---

## 三、完整 6 步工作流详解

在所有命令与说明中，统一使用以下动态路径占位符：
- `<PROJECT_ROOT>`：被治理的目标项目仓库根目录
- `<AG_REPO_ROOT>`：`ag` 仓库根目录
- `<WORKTREE>`：`ag_start` 创建的隔离工作树目录（位于 `<AG_HOME>/worktrees/<PROJECT_KEY>/<TASK_ID>`）
- `<AG_HOME>`：`ag` 状态主目录（默认 `~/.ag`）
- `<PYTHON_EXECUTABLE>`：Python 解释器路径（如 `python`）

### 第 1 步：登记仓库（Enroll）

首次在目标项目使用 `ag` 时，先保持 `<PROJECT_ROOT>` 的 Git 状态干净，然后执行登记：

- **MCP 调用**：`ag_enroll(root="<PROJECT_ROOT>")`
- **CLI 命令**：
  ```powershell
  python -m ag enroll <PROJECT_ROOT>
  ```

**执行效果**：
- 在 `<AG_HOME>/projects/<PROJECT_KEY>/` 下初始化项目治理数据库与目录。
- 自动将 `.data/` 与 `.ag-check/` 写入 `<PROJECT_ROOT>/.git/info/exclude`（不会污染项目本身的 `.gitignore`）。
- 若 `<AG_HOME>/projects/<key>/ticket.md` 尚不存在，自动生成一份带中文说明的初始票据模板。
- 安装 Git `pre-commit` 钩子，防止在任务进行中意外向主仓直接提交。

---

### 第 2 步：编写启动票（`<AG_HOME>/projects/<key>/ticket.md`）

每次开工前，必须先编辑 `<AG_HOME>/projects/<key>/ticket.md`。这是本轮任务的唯一权威意图文档（详细提炼方法参见 [`skills/ag-anchor/SKILL.md`](../ag-anchor/SKILL.md)）。

#### 标准写法模板：

```markdown
# 票

## 意图
做成之后：用大白话写清楚这轮改动完成后，用户或系统能观察到的真实结果（明确改什么对象、用什么机制、包含与排除什么边界）。

anchor: 在哪几个具体模块或文件中建立什么机制：当满足什么正常条件时产生什么预期结果，若遇到什么异常或违规边界则如何拦截或拒绝
anchor: 在哪个交互或数据链路上收敛什么行为：当输入或状态变化时如何流转，若出现越界或缺失则如何兜底保护

## 红线
- 针对本票目标的具体禁令 1：明确指出不能破坏的接口契约、不能触碰的目录或严禁引入的做法。
- 针对本票目标的具体禁令 2：聚焦本次改动的真实高风险边界（3~5 条即可，严禁写“代码要规范”“不能有 bug”等空泛套话）。
```

#### 写票三大高分要点（决定 `ticket` 席位能否一次通过）：
1. **`## 意图` 大白话讲清业务终点**：必须包含以 `做成之后：`（或 `固定:`）开头的可观测完成态描述，不要只写半句口号。
2. **`anchor:` 具备正反完整行为链路**：每条 `anchor:` 都是不少于 20 字的带动词陈述句，写清**“在哪改 + 正常情况怎么走（当……时……）+ 异常/边界情况怎么拦（若……则……）”**。
3. **`## 红线` 窄化聚焦**：只写与本票强相关的具体硬约束，不要堆砌放之四海皆准的废话，也不要原样照抄上一张票的红线。

---

### 第 3 步：开工建工地与开票独立审票（`ag_start`）

写好 `<AG_HOME>/projects/<key>/ticket.md` 后，启动任务：

- **MCP 调用**：`ag_start(root="<PROJECT_ROOT>", portrait="做成之后：...")`
- **CLI 命令**：
  ```powershell
  python -m ag start <PROJECT_ROOT> --portrait "做成之后：..."
  ```

**底层发生了什么？**
1. **主仓冻结（Canonical Freeze）**：`<PROJECT_ROOT>` 下所有受跟踪文件被设为只读（Windows 下附加可恢复的当前用户写拒绝 ACL），防止 AI 误改主仓。
2. **创建隔离工作树 `<WORKTREE>`**：在 `<AG_HOME>/worktrees/<PROJECT_KEY>/<TASK_ID>` 创建独立 Git 工作树。此时 `<WORKTREE>` 也处于初始冻结状态，等待用户确认意图图后解冻。
3. **封存红线**：提取 `## 红线` 与硬锚点（`anchor!:`），封存写入 `<AG_HOME>/projects/<key>/redlines.copy`。
4. **0-Token 脚本预筛 + 无状态 `ticket` 审票**：
   - 本地 `ticket_prescreen` 先检查意图长度、锚点正反链路完整性、套话红线与跨票重复率。
   - 若配置了独立审核模型，开启全新无状态的 `ticket` 线程（分配独立 `thread_id`），从 **目标清晰度（`goal_clarity`）**、**锚点链路完整性（`anchor_chain`）**、**红线聚焦度（`redline_focus`）** 三个维度（0-10 分，均 `>= 7` 且无实际违规或关键缺证方可通过）独立审票，并复述它所理解的目标（`understood_goal`）。`doubts` 中明确标记的普通建议进入 `advisories`，不单独阻塞。
   - 若审票未通过（`rejected`），直接根据返回的 `reasons`、`suggestions` 和 `doubts` 修改 `<AG_HOME>/projects/<key>/ticket.md`，然后**再次运行 `ag_start`** 即可原地重封存、重审，无需先 `abandon`。

---

### 第 4 步：用户确认意图图并解冻工作树（`confirm-map`）

`ag_start` 成功后，AI **必须立即停手**，将返回的 `anchor_preview`（以及 `ticket_review` 的审票结果）展示给用户，并等待用户确认。

- 用户检查无误后，执行解冻命令：
  ```powershell
  python -m ag confirm-map <PROJECT_ROOT>
  ```
- **铁律**：`confirm-map` 代表人类的显式授权，AI 严禁自己调用 `confirm-map`。执行后，`<WORKTREE>` 解除只读冻结，正式进入可施工状态。

---

### 第 5 步：在 `<WORKTREE>` 隔离施工与编写 `.ag-check/` 一次性自检

1. **只在 `<WORKTREE>` 修改产品代码**：
   - 一切文件新增、修改、删除都在 `<WORKTREE>` 中完成，绝不触碰 `<PROJECT_ROOT>`。
2. **多 Worker 协同（可选，最多 3 个 Worker）**：
   - 若任务需要拆分给子代理执行，使用 `worker-create` 创建中立的 Worker 任务档案：
     ```powershell
     python -m ag worker-create <PROJECT_ROOT> --worker-id <WORKER_ID> --portrait "子任务目标..." --anchor "..." --write-allow <RELATIVE_PATH>
     ```
   - 每个 Worker 严格在自己的 `write_allow` 白名单内修改 `<WORKTREE>`，完成后在 `<WORKTREE>.artifacts/workers/<WORKER_ID>/result.json` 写入 `ag.worker.result.v1` 格式的回执，主控通过 `python -m ag worker-read <PROJECT_ROOT> <WORKER_ID>` 验收。
3. **在 `<WORKTREE>/.ag-check/` 编写一次性验证脚本**：
   - 在 `<WORKTREE>/.ag-check/` 下创建针对本票改动与红线边界的验证脚本（例如 `<WORKTREE>/.ag-check/check_ticket.py`）并运行通过。
   - `.ag-check/` 已自动被 Git 忽略，且会在 `ag_finish` 时随 `<WORKTREE>` 一起销毁，不会留在主仓变成下一轮 AI 作弊的“常驻答案库”。

---

### 第 6 步：交卷验货（`ag_verify`）与原子合入（`ag_finish`）

施工与自检完成后，发起正式交卷验货：

- **MCP 调用**：`ag_verify(root="<PROJECT_ROOT>")`
- **CLI 命令**：
  ```powershell
  python -m ag verify <PROJECT_ROOT>
  ```

**`ag_verify` 检验流水线**：
1. 检查 `<PROJECT_ROOT>` 是否保持干净（若被污染则立即报 `canonical-dirty` 拒绝）。
2. 检查所有创建的 Worker 是否均已提交合规的 `result.json`。
3. 运行本地 `pack_prescreen`（Python 语法树编译检查、红线路径/关键字碰撞扫描、投机词扫描、`.ag-check/` 真实断言检查）。
4. 运行命中修改路径的历史回归探针（`probes`）。
5. 调用单次无状态 `switch` 终审席位：对预标好精确 `path:line` 行号的 `git diff`、裁剪后源码窗口与 `.ag-check/` 脚本进行独立代码终审。实际违规或关键缺证仍拒绝；自动记录的问题位置先作为 `pending-behavior` 线索，用 `probe calibrate` 验证修复前失败、修复后通过后才成为行为探针，不能以文本消失冒充修复。

**合入或放弃**：
- 当 `ag_verify` 通过后，执行原子合入：
  - **MCP 调用**：`ag_finish(root="<PROJECT_ROOT>")`
  - **CLI 命令**：
    ```powershell
    python -m ag finish <PROJECT_ROOT>
    ```
  - **效果**：将 `<WORKTREE>` 的提交以 `--ff-only` 快进合入 `<PROJECT_ROOT>`，解除 `<PROJECT_ROOT>` 只读冻结，销毁 `<WORKTREE>` 及其中的一次性自检脚本，并更新 `<AG_HOME>/projects/<key>/ticket.md` 的 `## 现场` 为已完成。
- 若中途决定取消当前任务：
  - **MCP 调用**：`ag_abandon(root="<PROJECT_ROOT>")`
  - **CLI 命令**：
    ```powershell
    python -m ag abandon <PROJECT_ROOT>
    ```
  - **效果**：安全丢弃 `<WORKTREE>`，立即恢复 `<PROJECT_ROOT>` 的正常读写权限。
