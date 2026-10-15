# ag (AutoGovern)

**简体中文** | [English](README.en.md)

面向 AI 编程（Vibe Coding）的本地工程交付护栏与独立审核底座（MCP + CLI）。

三条绝不混用的正交轨道：**ship（交货）** · **lift（抬正确率）** · **see（看见）**。
只有 `ship` 可以设置 `product` 状态或拒绝 `finish`；`lift` 与 `see` 仅提供建议或客观观测，绝不越权拦门。

---

## 自带 AI 技能包与入口导航

- 🧭 **AI 与用户总入口锚点（`AGENTS.md`）**：[`AGENTS.md`](AGENTS.md)
- 📘 **使用指南与 6 步工作流技能（`ag-guide`）**：[`skills/ag-guide/SKILL.md`](skills/ag-guide/SKILL.md)
- ⚙️ **AI 引导式配置技能（`ag-config`）**：[`skills/ag-config/SKILL.md`](skills/ag-config/SKILL.md)
- 🛠️ **常见问题排障手册技能（`ag-troubleshooting`）**：[`skills/ag-troubleshooting/SKILL.md`](skills/ag-troubleshooting/SKILL.md)
- 🎯 **意图锚点与写票规范技能（`ag-anchor`）**：[`skills/ag-anchor/SKILL.md`](skills/ag-anchor/SKILL.md)

---

## 核心交付闭环

主仓（`<PROJECT_ROOT>`）永远不是施工现场，所有代码修改必须在隔离工作树（`<WORKTREE>`）中完成：

```text
ag_status → ag_start → confirm-map → 仅在 <WORKTREE> 内施工 → ag_verify → ag_finish
```

- **主仓只读冻结（Canonical Freeze）**：当任务开启时，`ag` 会自动冻结主仓（`<PROJECT_ROOT>`）中受 Git 跟踪的文件（Windows 下添加当前用户可恢复的 ACL 拒绝写入项，其他系统清除用户写权限位）。若主仓在任务期间变脏，`ag_verify` 会立即拒绝并记录 `canonical-dirty`，不再执行后续测试、探针与审核。
- **禁止常驻测试答案库**：不要在仓库中保留常驻 `tests/` 目录。本票的一次性验证脚本统一写在工作树的 `<WORKTREE>/.ag-check/` 下（随工作树合入后自动销毁），避免旧测试成为下一轮 AI 投机凑分的固定答案库。
- **验证与守门（`ag_verify`）**：依次运行登记的轻量命令（若已配置）、路径命中的历史探针（`probe`），以及单次独立终审席位（**`switch`**）。只有已配置且未通过（`rejected` 或 `void`）的 `switch` 或亮红灯的探针（`probe_red`）会拒绝 `ag_finish`。

### 快速开始命令

```powershell
# 1. 登记目标仓库（自动将 .data/ 与 .ag-check/ 写入本地 .git/info/exclude 并生成初始票据模板）
python -m ag enroll <PROJECT_ROOT>

# 2. 查看配置向导与就绪诊断（AI 可据此引导用户完成配置）
python -m ag config <PROJECT_ROOT>

# 3. 启动 stdio MCP 服务
python -m ag mcp
```

审计与状态存储在 `<AG_HOME>/projects/<PROJECT_KEY>/`（默认 `<AG_HOME>` 为 `~/.ag`）：
- 数据库：`ag.sqlite`
- 任务步进链：`<AG_HOME>/projects/<PROJECT_KEY>/tasks/<TASK_ID>.json`（可通过 `ag_status.timeline_path` 或 `python -m ag critic-log <PROJECT_ROOT>` 查看）

---

## 意图锚点与启动票（`.data/ticket.md`）

开工（`ag_start`）前必须在主仓准备好 `<PROJECT_ROOT>/.data/ticket.md`（首次 `enroll` 会自动生成模板并加入本地 `.git/info/exclude`）。

- `## 意图`：用大白话写明本票业务目标与可观察的完成态，保持原文不变。
- `## 红线`：`ag_start` 会将 `## 红线` 及硬锚点（`anchor!:`）封存到 `.data/redlines.copy`，并归档至 `.data/tickets/<TASK_ID>.md`。
- `## 现场`：由 `start`、`verify`、`finish` 自动刷新任务状态，不覆盖 `## 意图` 与已封存的 `## 红线`。
- **强制人工确认门禁（`confirm-map`）**：`ag_start` 后工作树处于冻结状态。AI 必须先将 `anchor_preview`（即 `.data/ticket.md` 全文）展示给用户，等待用户明确回复“确认”后，再执行 `confirm-map` 解冻工作树。AI 严禁自行偷偷调用 `confirm-map`。

### 锚点类型

```text
anchor: 在目标模块建立登录行为闭环：当输入正确密码时允许登录，若输入错误密码则立即拒绝并提示错误
anchor!: 严禁修改原有的鉴权中间件签名
```

- `anchor:` 软注意力锚点（至少 20 字的完整行为陈述句，锁住“输入/触发 → 正向结果 + 反向/边界拒绝结果”的完整链路）。
- `anchor!:` 硬规则锚点（仅当源于用户或项目明确规定如“必须/禁止/不要”时使用，AI 严禁凭空猜测捏造硬锚点）。
- `anchor~:` 可探索未知项；`anchor?:` 阻塞性未知项（开工前先问清）；`anchor=:` AI 替用户选的合理默认项；`anchor-:` 避开区域；`anchorx:` 已废弃锚点。

---

## 一前一后无状态审核架构（`ship-12`, `ship-13`, `lift-18`, `see-15`）

`ag` 采用 **0-Token 本地通用脚本确定性预筛 + 一前一后（`ticket` 开票审 + `switch` 交卷守门）无状态 DS 审核**架构，将大模型注意力 100% 集中在语义判断上：

1. **前门：开票独立审票席（`ship-13`，`ticket` 席位）**
   - 每次 `ag_start` 先由本地脚本 0 Token 执行 `ticket_prescreen`（检查字数、正反完整链路词、空泛套话红线、连续票序 `ticket_seq` 与跨票重合率），写入 `script_digest`。
   - 随后启动全新、无上下文历史的独立 `ticket` 审核线程（`thread_id`），从三个维度打分（`0-10`，`>= 7` 通过）：
     - `goal_clarity`：仅凭本票能否看懂业务目标，并用大白话独立复述 `understood_goal`（有任何疑惑即判不通过）。
     - `anchor_chain`：意图锚点是否锁住包含正向与反向/边界拒绝的完整行为链路。
     - `redline_focus`：红线是否合理且范围收缩聚焦。
   - 若已配置审核且未通过，`confirm-map` 会拒绝解冻工作树；此时直接修改 `.data/ticket.md` 并再次运行 `ag_start` 即可原地重封存、重审。
   - **多轮反偷懒严审（`lift-18`）**：连续第 3+ 张票（`ticket_seq >= 3`）自动开启严审模式，本地脚本硬核校验审核方是否照抄原文、跨票评语雷同或全满分敷衍放水（`lazy-review`），检出即自动触发重审。
2. **后门：交卷单次守门与考卷瘦身（`see-15`，单次 `switch` 席位）**
   - `ag_verify` 先由本地脚本 0 Token 执行 `pack_prescreen`（Python/JSON 语法校验、红线文件名/反引号标识符碰撞扫描、吞异常/塞 mock 作弊扫描、`.ag-check/` 断言检查）。
   - 自动为 `git diff` 逐行预标真实源文件行号（`path:line`），并对超过 `12,000` 字符的大文件仅截取文件头 + 改动上下文窗口，只调用 **1 次 `switch`** 完成最终裁决，大幅降低 Token 消耗。

---

## 标准配置文件格式（`critic.json`）

通过以下命令生成或查看当前配置状态与标准模板（AI 会自动读取其中的 `config_guide` 指导用户完成配置）：

```powershell
python -m ag config <PROJECT_ROOT>
```

配置文件支持**全局级**（`<AG_HOME>/critic.json`，默认 `~/.ag/critic.json`，配置一次所有项目通用）与**项目级**（`<AG_HOME>/projects/<PROJECT_KEY>/critic.json`，覆盖全局配置）。API Key 存放在系统环境变量中，**切勿将密钥明文写入 `critic.json`**：

```json
{
  "enabled": true,
  "endpoint": "https://api.deepseek.com",
  "model": "deepseek-chat",
  "api_key_env": "AG_CRITIC_API_KEY",
  "timeout": 60,
  "worker_model": "claude",
  "allow_same_family": false
}
```

详细配置说明与 MCP 客户端挂载方式请查阅 [`skills/ag-config/SKILL.md`](skills/ag-config/SKILL.md)。

---

## 安装自带技能包（Skills）

一键将全部 4 个内置技能包（`ag-anchor`、`ag-guide`、`ag-config`、`ag-troubleshooting`）安装到用户技能目录：

```powershell
python -m ag install-skill --target codex
python -m ag install-skill --target grok
```

---

## 多 Worker 隔离协作流

在已确认意图图（`confirm-map`）的活跃工作树中，可创建最多 3 个与厂商无关的 Worker 任务档案：

```powershell
python -m ag worker-create <PROJECT_ROOT> --portrait "做成之后：..." --anchor "保持原有鉴权行为不变" --hard-anchor "严禁运行 ag finish" --write-allow src/auth --write-allow src/core
```

- 档案生成在 `<AG_HOME>/worktrees/<PROJECT_KEY>/<TASK_ID>.artifacts/workers/<WORKER_ID>/` 下（包含 `task.json` 与 `TASK.md`）。
- Worker 完成后写入符合 `ag.worker.result.v1` 契约的 `result.json`，可通过以下命令校验：
  ```powershell
  python -m ag worker-read <PROJECT_ROOT> <WORKER_ID>
  ```
- 也可通过外部 Provider 运行并实时追踪日志：
  ```powershell
  python -m ag worker-run <PROJECT_ROOT> <WORKER_ID> --provider grok
  python -m ag worker-log <PROJECT_ROOT> <WORKER_ID>
  python -m ag checker-log <PROJECT_ROOT> switch
  ```

---

## 三维策略轨道一览（`ship` / `lift` / `see`）

- **`ship`（交货闸）**：唯一拥有阻断 `finish` 与设置 `product` 权力的轨道（含主仓冻结、工作树隔离、`ship-12` 红线封条、`ship-13` 开票独立审票闸、探针与 `switch` 终审）。
- **`lift`（抬正确率建议）**：
  - `lift-12`：意图锚点注意力跟踪。
  - `lift-13` / `lift-14`：变更感知摘要与任务快照。
  - `lift-15`（红线回声）：对比上一票与本票红线，提醒被删减的旧红线。
  - `lift-16`（捷径嗅探）：扫描新增代码中的吞异常、引 mock、占位符等应试假实现信号。
  - `lift-17`（可拔除建议）：检测新增子模块的跨文件引用触点数，引导单点挂载。
  - `lift-18`（多轮审票反偷懒）：跟踪连续票序并在第 3+ 票开启反敷衍严审。
- **`see`（客观观测）**：
  - `see-10` / `see-11`：重复样式症状与所有权归属透视。
  - `see-12`（强推与反向引用）：统计跨语言类型/Lint 压制符净增与反向 import。
  - `see-13`（考卷净荷与防抖）：观测实时日志体积、红线封存状态与 `.ag-check` 大文件过滤。
  - `see-14`（票据与红线轨迹）：汇总 `.data/tickets/` 历史票据与高频红线分布。
  - `see-15`（一前一后精简考卷）：记录单次 `switch` 与窗口裁剪节省的字符与 Token 账本。
