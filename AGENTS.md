# AG 全局入口与 AI 行动指南 (`AGENTS.md`)

欢迎进入 `ag`！本文件是 AI 编程助手（Codex、Claude、Grok、Cursor 等）与开发者的顶层入口锚点。当用户打开本仓库或将 `ag` 接入目标项目时，AI 应首先阅读本文件并按下方导航引导用户完成配置、使用与排障。

---

## 1. 项目定位（`ag` 是什么）

**一句话定位**：`ag` 是面向 AI 编程（Vibe Coding）的**本地工程交付护栏与独立审核底座（MCP + CLI）**。

它通过 **主仓冻结（Canonical Freeze）+ 独立工作树（`<WORKTREE>`）隔离施工 + 启动票意图锚点与红线封存（`<PROJECT_ROOT>/.data/ticket.md`）+ 0-Token 本地脚本预筛 + 一前一后（`ticket` 开票审 + `switch` 交卷守门）无状态 DS 审核 + 一次性验证（`<WORKTREE>/.ag-check/`）**，从物理机制上解决 AI 编程的三大核心痛点：

1. **防止改乱主仓与半途污染**：主分支检出区（`<PROJECT_ROOT>`）在任务期间物理只读冻结；所有修改强制发生在隔离工作树 `<WORKTREE>`，验收通过后才以 `--ff-only` 原子合入主仓。
2. **防止目标漂移与偷删红线**：开工前强制在 `<PROJECT_ROOT>/.data/ticket.md` 锁定业务意图、正反向行为链路锚点（`anchor:`）与聚焦红线（`## 红线`），封存为不可篡改的 `.data/redlines.copy`，并必须经用户显式执行 `confirm-map` 确认后才解冻工作树。
3. **防止“自己考自己”写假测试凑分**：废除常驻 `tests/` 答案库，每张票在 `<WORKTREE>/.ag-check/` 现场编写针对本票结果的一次性自检脚本（合入即销毁），配合异构/无状态的 `ticket`（开票三维审票）与 `switch`（交卷代码终审 + 自动种回归探针 `probes`）守住交付底线。

---

## 2. 文档与自带 Skill 导航

需要了解具体用法、配置方式或排查报错时，请直接查阅以下专题文档：

- 📘 **使用指南（项目干什么 & 完整 6 步工作流）**：[`docs/guide.md`](docs/guide.md)
- ⚙️ **配置指南（标准 `critic.json` 配置文件格式 & AI 引导配置）**：[`docs/configuration.md`](docs/configuration.md)
- 🛠️ **排障手册（常见报错码、原因分析与一步修复方案）**：[`docs/troubleshooting.md`](docs/troubleshooting.md)
- 🤖 **自带 AI 技能（指导 AI 提炼意图锚点与执行全流程）**：[`skills/ag-anchor/SKILL.md`](skills/ag-anchor/SKILL.md)
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
该操作会自动将 `.data/` 与 `.ag-check/` 写入 `<PROJECT_ROOT>/.git/info/exclude`（**零污染主仓 `.gitignore`**），并在缺少票据时自动生成初始 `<PROJECT_ROOT>/.data/ticket.md` 模板。

### 第三步：引导配置独立 DS 审核席位（按需）
若用户希望启用独立大模型审核（`ticket` 开票审 + `switch` 交卷守门）但 `reviewer_ready: false`：
1. 读取 `config_guide.global_config_path`（默认 `<AG_HOME>/critic.json`）或 `config_guide.project_config_path`，以及 `config_guide.template` 和 `config_guide.fields`。
2. 指导用户按标准 JSON 格式填写 `endpoint`、`model`、`api_key_env` 等字段（详见 [`docs/configuration.md`](docs/configuration.md)）。
3. 检查 `api_key_present` 布尔值，指导用户在终端或 MCP 配置中设置对应的环境变量（**安全铁律：AI 绝不向用户索要、读取或在任何日志中打印 API Key 明文**）。

### 第四步：严格执行 6 步受控交付闭环
1. **写票**：协助用户编写 `<PROJECT_ROOT>/.data/ticket.md`（包含大白话 `## 意图`、带正反完整行为链路的 `anchor:`、窄化聚焦的 `## 红线`）。
2. **开票与审票**：调用 `ag_start`（触发本地 0-Token 脚本预筛 + 无状态 `ticket` 席位三维审票；若被打回则修改 `.data/ticket.md` 后重跑 `ag_start`）。
3. **等待用户确认意图图**：向用户完整展示 `anchor_preview` 及 `anchor_preview_path`，**立即停手等待用户确认**。用户确认后由用户执行 `python -m ag confirm-map <PROJECT_ROOT>` 解冻 `<WORKTREE>`（AI 严禁替用户自调 `confirm-map`）。
4. **隔离施工与一次性自检**：仅在 `<WORKTREE>` 内修改代码（复杂任务可用 `ag worker-create` 拆分最多 3 个 Worker），并在 `<WORKTREE>/.ag-check/` 下编写针对本票结果的一次性自检脚本。
5. **交卷验货**：调用 `ag_verify`（执行本地预筛、历史回归探针 `probes`、`.ag-check/` 验证与单次无状态 `switch` 终审）。
6. **原子合入或放弃**：验收通过后调用 `ag_finish` 快进合入 `<PROJECT_ROOT>` 并自动清理 `<WORKTREE>` 与 `.ag-check/`；若任务无价值或需推翻重来，调用 `ag_abandon` 安全解冻主仓。
