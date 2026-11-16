# AG 全局入口与 AI 行动指南 (`AGENTS.md`)

欢迎进入 `ag`！本文件是 AI 编程助手（Codex、Claude、Grok、Cursor 等）与开发者的顶层入口锚点。当用户打开本仓库或将 `ag` 接入目标项目时，AI 应首先阅读本文件并按下方导航引导用户完成配置、使用与排障。

---

## 1. 项目定位（`ag` 是什么）

**一句话定位**：`ag` 是面向 AI 编程（Vibe Coding）的**本地工程交付护栏与独立审核底座（MCP + CLI）**。

它通过 **主仓冻结（Canonical Freeze）+ 独立工作树（`<WORKTREE>`）隔离施工 + 启动票意图锚点与红线封存（`<AG_HOME>/projects/<key>/ticket.md`）+ 0-Token 本地脚本预筛 + 一前一后（`ticket` 开票审 + `switch` 交卷守门）无状态 DS 审核 + 一次性验证（`<WORKTREE>` 内现场生成的一次性自检脚本）**，从物理机制上解决 AI 编程的三大核心痛点：

1. **防止改乱主仓与半途污染**：主分支检出区（`<PROJECT_ROOT>`）在任务期间物理只读冻结；所有修改强制发生在隔离工作树 `<WORKTREE>`，验收通过后才以 `--ff-only` 原子合入主仓。
2. **防止目标漂移与偷删红线**：默认 `single` 在 `<AG_HOME>/projects/<key>/ticket.md` 锁定业务意图、正反向行为链路锚点（`anchor:`）与聚焦红线（`## 红线`）；显式 `long` 以可直接维护的 Markdown 长票保存持续目标与来源。两种类型均须经独立审票、用户本人 `confirm-map` 与真实解冻后才 ready；长期票确认须携带所见 `--preview`。旧 SQLite 长票只读保留，显式迁移后才切换权威。
3. **防止“自己考自己”写假测试凑分**：废除常驻 `tests/` 答案库，每张票在 `<WORKTREE>/.ag-check/` 现场编写针对本票结果的一次性自检脚本（合入即销毁），配合异构/无状态的 `ticket`（开票三维审票）与 `switch`（交卷代码终审 + 自动种回归探针 `probes`）守住交付底线。

---

## 2. 自带 Skill 套件导航（职责分离，按需加载）

`ag` 将使用说明、配置引导、问题排障与意图写票拆分为 `skills/` 下的 **4 套独立自带 Skill**（执行 `python -m ag install-skill --target codex|grok` 可一键全量安装）：

- 📘 **使用指南 Skill（项目是干什么的 & 6 步完整工作流）**：[`skills/ag-guide/SKILL.md`](skills/ag-guide/SKILL.md)
- ⚙️ **配置引导 Skill（`config.json` 的 `critic` 段、全局兼容配置、环境变量与 AI 引导配置）**：[`skills/ag-config/SKILL.md`](skills/ag-config/SKILL.md)
- 🛠️ **问题排障 Skill（常见报错码、原因分析与一步修复方案）**：[`skills/ag-troubleshooting/SKILL.md`](skills/ag-troubleshooting/SKILL.md)
- 🎯 **意图锚点 Skill（写票规范、正反完整行为链路 `anchor:` 与窄化红线）**：[`skills/ag-anchor/SKILL.md`](skills/ag-anchor/SKILL.md)
- 📄 **架构与命令速查**：[`README.md`](README.md)

---

## 3. 路径变量约定

为保证跨平台与多机环境开箱即用，`ag` 全系文档与配置统一使用以下动态变量占位符（严禁硬编码个人电脑目录路径）：

| 占位符 | 含义说明 |
| :--- | :--- |
| `<PROJECT_ROOT>` | 被治理的目标项目仓库根目录（Canonical Checkout，任务期间只读冻结） |
| `<AG_REPO_ROOT>` | `ag` 仓库自身的根目录（若通过源码 `PYTHONPATH=<AG_REPO_ROOT>/src` 方式运行） |
| `<WORKTREE>` | `ag_start` 生成的当前任务隔离工作树路径（通常位于 `<AG_HOME>/worktrees/<PROJECT_KEY>/<TASK_ID>`） |
| `<AG_HOME>` | `ag` 状态、审计库与全局配置主目录（默认 `~/.ag`，可通过 `AG_HOME` 环境变量覆盖） |
| `<PYTHON_EXECUTABLE>` | 当前运行环境的 Python 解释器路径（如 `python` 或虚拟环境解释器路径） |

---

## 4. AI 接待新用户的标准动作（AI Onboarding 铁律）

恢复任务先用 `python -m ag delivery <PROJECT_ROOT> --task-id <TASK_ID>` 或 MCP `ag_delivery` 读取共同目标、本票贡献、已验证进展、未完成项及下一动作。完整功能可在一票内跨必要模块分阶段实现；路线调整说明原因即可，减少承诺或改变硬边界须用户决定。真正独立的续作使用明确 `continuation_of`，不自动串联无关票。

`status/delivery` 只读，完整诊断用 `ag_see`，安装修复用 `enroll/config`。`confirm-map` 必须由用户亲自执行，真实解冻完成后才 `ready`；失败保留可恢复状态。交卷选取本票 `.ag-check/check_*.py` 并绑定脚本、候选和审核。历史按时间和容量分卷，先校验发布再回收闭票散档；活动票、准备资料、审计与备份保留。

当用户第一次在项目中接入 `ag`，或询问“怎么配置 / 怎么开始 / 为什么报错”时，AI 必须按以下 4 步主动引导：

### 第一步：诊断环境与配置状态
运行 MCP 工具 `ag_status(root="<PROJECT_ROOT>")` 或 CLI 命令：
```powershell
python -m ag config <PROJECT_ROOT>
```
读取返回 JSON 中的 `onboarding` 与 `config_guide` 字段，判断项目是否已登记（`enrolled`）、独立审核席位是否就绪（`reviewer_ready`）以及下一步动作（`next_action`）。

### 第二步：零污染登记目标仓库
若项目尚未登记（`not-enrolled`），执行 `ag_enroll(root="<PROJECT_ROOT>")` 或：
```powershell
python -m ag enroll <PROJECT_ROOT>
```
该操作会自动把 ag 的本地忽略项写入 `<PROJECT_ROOT>/.git/info/exclude`（**零污染主仓 `.gitignore`**），并在缺少票据时于 ag 家里自动生成初始 `<AG_HOME>/projects/<key>/ticket.md` 模板。票只住在 ag 家里；若旧项目仍把 `ticket.md` / `tickets/` / `redlines.copy` 三样留在项目里，`ag_start` 会先逐份核对 SHA256 后一次性搬进新家并留一份可读的搬家记录，项目里不留任何 ag 门牌。

### 第三步：引导配置独立 DS 审核席位（按需）
若用户希望启用独立大模型审核（`ticket` 开票审 + `switch` 交卷守门）但 `reviewer_ready: false`：
1. 读取 `config_guide.global_config_path`（默认 `<AG_HOME>/critic.json`）或 `config_guide.project_config_path`，以及 `config_guide.template` 和 `config_guide.fields`。
2. 指导用户按标准 JSON 格式填写 `endpoint`、`model`、`api_key_env` 等字段（详见 [`skills/ag-config/SKILL.md`](skills/ag-config/SKILL.md)）。
3. 检查 `api_key_present` 布尔值，指导用户在终端或 MCP 配置中设置对应的环境变量（**安全铁律：AI 绝不向用户索要、读取或在任何日志中打印 API Key 明文**）。

### 第四步：严格执行 6 步受控交付闭环
1. **写票**：默认 single 协助用户编写 `<AG_HOME>/projects/<key>/ticket.md`（包含大白话 `## 意图`、正反完整行为链路 `anchor:` 与窄化红线）；跨轮目标显式 long，通过 `long create` 创建并直接维护 Markdown 权威。
2. **开票与审票**：调用 `ag_start`（long 显式 `ticket_type="long"` 加 `goal_id` 或 `long_file`），触发本地预筛与独立三维审票；被打回后修正相应权威 Markdown 再原地重审，保留失败历史。
3. **等待用户确认意图图**：向用户完整展示 `anchor_preview` 及 `anchor_preview_path`，**立即停手等待用户确认**。用户确认后由用户执行 `python -m ag confirm-map <PROJECT_ROOT>` 解冻 `<WORKTREE>`；long 须携带刚展示的 `--preview <TOKEN>`（AI 严禁替用户自调 `confirm-map`）。
4. **隔离施工与一次性自检**：仅在 `<WORKTREE>` 内修改代码（复杂任务可用 `ag worker-create` 拆分最多 3 个 Worker），并在 `<WORKTREE>/.ag-check/` 下编写针对本票结果的一次性自检脚本。
5. **交卷验货**：调用 `ag_verify`（执行本地预筛、历史回归探针 `probes`、`.ag-check/` 验证与单次无状态 `switch` 终审）。
6. **原子合入或放弃**：验收通过后调用 `ag_finish` 快进合入 `<PROJECT_ROOT>` 并自动清理 `<WORKTREE>` 与 `.ag-check/`；若任务无价值或需推翻重来，调用 `ag_abandon` 安全解冻主仓。

## 单票与 Markdown 长票

未指定类型时使用 `single`，保留现有单票工作流；需要跨多轮持续交付时显式选择 `long`。新长票以可直接编辑的 `long.md` 为意图权威。直接打开该文件即可阅读和维护目标，不需要手写 JSON，也不需要启动 HTML 面板。

长票首屏先说明交什么、怎样算完成、现在到哪、当前卡点和下一步，再用 Mermaid 展示主线。适用约束、现场依据、各轮贡献、变更与待定提案放在折叠段中。每轮已开子票链接到独立原票 `.md`；尚未开票的剩余节点明确标为未开。完结原票保留当时的承诺、用户原话和来源，后续进度摘要不能覆盖原票。

AI 每轮先读长票大纲，再读本轮原票和真实 `delivery` 回执，恢复未完成承诺、分支原因、返回节点和回归要求；收尾时只更新所需进度段。普通进度保留有效授权，目标或约束变化须记录旧→新、决定者、原因、影响、回归点和旧证据适用范围，再经独立复审和用户本人 `confirm-map`。待定提案保持待定，不能自动变成必做承诺。子票通过也不表示父目标已完成。

文件编辑时间与业务事件时间、实际核验时间分别记录。未核验变化标为待核验；读取文件或调整排版不会刷新核验时间。外部直接编辑后先重读，陈旧 token、坏引用、格式错误和意图冲突必须明确处理；不能覆盖外部改动、静默删除未知段落或把旧证据说成当前已验证。

旧 single 票保持兼容。旧 `long-goals.sqlite3` 及其历史导出仍可只读追查，显式迁移才创建新的 Markdown 权威，并标明旧数据的历史地位；转换失败保留原文与原史，不能新旧双改或继承不存在的授权。旧 HTML 面板退出默认开票和阅读指导。
