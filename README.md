# ag (AutoGovern)

**简体中文** | [English](README.en.md)

面向 AI 编程（Vibe Coding）的本地工程交付护栏与独立审核底座（MCP + CLI）。

当前版本：**v0.5.2**。

## v0.5.2 新能力

- **标准单票交付**：每张票独立审票、本人确认、隔离施工与验货；`continuation_of` 仅携带前票参考信息，不传递授权。

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

## v0.4 新能力

继 v0.3（交付护栏 + 独立审核底座）之后，v0.4 让 ag「越用越懂你的项目」，并把状态目录管得不膨胀、可回溯。

- **结构体检**：通用内核发现孤岛文件、假装配依赖、反向引用；多语言适配器表（Python / TS / Go / Rust / Java），仓里有什么语言就自动用哪套规则；只出事实不拦截。
- **一根配置 `config.json`**：项目所有开关汇到一份根配置——审核席位、体检适配器、防膨胀闸、48 条策略清单（带中文名 / 开关 / 可否关）；`python -m ag config-show <PROJECT_ROOT>` 一键看人读版。
- **跨会话复盘**：每张票归档「想解决什么 / 发现什么 / 做对 / 做错 + 教训」四段；项目红线册随票累积、开票自动喂给 AI；`python -m ag retro <PROJECT_ROOT>` 出人读复盘报告。新会话的 AI 不再从零开始。
- **防膨胀闸**：席位过程日志跑完即清、usage 计数滚动截断、`python -m ag prune <PROJECT_ROOT>` 压旧残留留索引——留结论、砍流水。
- **项目状态版本化**：`<AG_HOME>/projects/<key>` 是本地 git 仓，只跟踪结论与配置，误删可恢复。
- **改自己人工闸门**：改 ag 自身代码的票，switch 拒单后 finish 停下等 `python -m ag approve-self <PROJECT_ROOT> <TASK_ID>` 人工放行，杜绝「自己改自己没人拦」。

---

## v0.5.1 新能力

在 v0.4「越用越懂你的项目」与 v0.5 的问题发现、状态治理能力之上，v0.5.1 进一步修复交付、历史迁移和故障恢复缺陷。

- **孤岛清单（see-16）**：结构体检算出的孤岛文件（零入口可达、零引用）过去只埋在考卷 JSON 里看不见，现在 `ag_see` 报告里直接按语言列出每个孤岛的仓内相对路径与总数。只发现、只报告，不拦票、不替你判断该不该删。
- **复盘不再失忆**：每张票复盘的「想解决什么」过去恒为空（取主题只读 portrait，MCP 开票不传它），现在 portrait 空时自动从票档 `四段人话` 提取人话主题，且所有来源统一先清洗再落盘，顺带根治了一条考卷正文直接落盘的隐私隐患。
- **状态目录瘦身**：早期 `tasks/index.jsonl` 汇总保持兼容；当前 `prune` 先发布可回读校验的历史分卷再回收旧散档，索引只作可重建视图。
- **结构体检更准**：仓级版本戳 `layout_version` + 版本驱动迁移链；TS/JS 相对导入补全（`./x`、`../x` 自动补 `.ts/.tsx` 与 `index.*`）；ESM `./x.js` 找不到产物时回退同名 `.ts` 真源码——前端引用链不再断、孤岛不再误判。

---

## 任务事实与连续交付

`python -m ag delivery <PROJECT_ROOT> --task-id <TASK_ID>`（MCP `ag_delivery`）只读查询活动票或归档票，输出完整目标、本票贡献、已验证结果、未完成项、阻塞、建议、下一动作、授权和解冻状态，以及报告与候选的来源。不存在的票返回 `task-not-found`；失败、访问锚点或施工开始不会变成已完成。相同报告的兼容席位不重复统计，复盘保留本票所有拒绝与通过，不推断所有拒绝都是误报。

完整功能可跨必要模块并在一票内分阶段完成；减少承诺或改变硬边界须等待用户决定。只有真正独立交付的续作才在 `spec.json` 中填写 `continuation_of`，开票时可用 `--contribution` 描述本票贡献，明确携带共同目标和剩余结果。

`status` 不再顺带安装、迁移、写票或运行完整体检；诊断用 `ag_see`，修复安装用 `enroll/config`。每张票由用户亲自执行 `confirm-map`，AI 不得代调。命令立即在 stderr 报告阶段，重验当前票、审核、配置、Git 身份与冻结状态；实际恢复全部工作树文件写权限后才 `ready`，解冻失败保留授权并允许重试。交卷按本票实际 `.ag-check/check_*.py` 选择检查，并将脚本摘要、候选和报告绑定。

验货和终审使用包含当前产品代码与 `.ag-check` 的同一候选快照；回执同时记录不含临时检查的 `product_tree`，用于核对最终提交。候选计算不修改实际暂存区；误暂存或跟踪的 `.ag-check` 会被拒绝，临时检查不会进入产品提交。

历史正本采用 `history/current.jsonl` 与按月、容量分卷的 JSONL；活动票面和指针保留可读文件。`prune` 对闭票时间线、票档、会话与对应旧审核事件先写临时分卷，刷新、回读校验、原子发布，再回收来源；索引可重建。旧格式继续可读，未知格式、活动现场、`preparations/`、`audits/` 和用户备份保留，写失败明确报错。自动审核指针先保留为待行为核查线索，`probe calibrate` 用真实修复前后命令对照后才能把它作为行为探针。命令探针默认 30 秒超时，可在观测中写 `timeout_s`（1 到 1800 的整数秒）；非法值在 `probe insert` 和 `calibrate` 时被拒绝，探针库中存量的非法值判红。

`history-corrupt`：`current.jsonl` 或某个分卷中有一行不是合法 JSON、schema 不对或校验和不符。读取时跳过该行，其余记录照常可读，坏行不会让任何记录凭空出现；`status` 的 `hazards` 含 `history-corrupt`，`history_issues` 列出 `path` 与 `line`（从 1 起算）；`delivery` 的 `blockers` 含同名条目，`next_action` 不会是 `finish`。`start`、`verify`、`finish`、在坏 `current.jsonl` 上续写、需要生成编号的写入以及 `prune` 都会拒绝，并写明 `<文件> line <行号>`。ag 不会自动删除或改写坏行：先备份，人工核对并修复（或移走）报出的行，再重试。

## 核心交付闭环

主仓（`<PROJECT_ROOT>`）永远不是施工现场，所有代码修改必须在隔离工作树（`<WORKTREE>`）中完成：

```text
ag_status → ag_start → 用户本人 confirm-map → ready → 仅在 <WORKTREE> 内施工 → ag_verify → ag_finish
```

- **主仓只读冻结（Canonical Freeze）**：当任务开启时，`ag` 会自动冻结主仓（`<PROJECT_ROOT>`）中受 Git 跟踪的文件（Windows 下添加当前用户可恢复的 ACL 拒绝写入项，其他系统清除用户写权限位）。若主仓在任务期间变脏，`ag_verify` 会立即拒绝并记录 `canonical-dirty`，不再执行后续测试、探针与审核。
- **禁止常驻测试答案库**：不要在仓库中保留常驻 `tests/` 目录。本票的一次性验证脚本统一写在工作树的 `<WORKTREE>/.ag-check/` 下（随工作树合入后自动销毁），避免旧测试成为下一轮 AI 投机凑分的固定答案库。
- **验证与守门（`ag_verify`）**：依次运行登记的轻量命令（若已配置）、路径命中的历史探针（`probe`），以及单次独立终审席位（**`switch`**）。只有已配置且未通过（`rejected` 或 `void`）的 `switch` 或亮红灯的探针（`probe_red`）会拒绝 `ag_finish`。

### 快速开始命令

```powershell
# 1. 登记目标仓库（自动将 .ag-check/ 写入本地 .git/info/exclude 并生成初始票据模板）
python -m ag enroll <PROJECT_ROOT>

# 2. 查看配置向导与就绪诊断（AI 可据此引导用户完成配置）
python -m ag config <PROJECT_ROOT>

# 3. 启动 stdio MCP 服务
python -m ag mcp
```

审计与状态存储在 `<AG_HOME>/projects/<PROJECT_KEY>/`（默认 `<AG_HOME>` 为 `~/.ag`），整个目录是一个本地 git 仓——只跟踪结论与配置（票文、红线册、复盘、config.json），不跟踪流水日志；每次 `finish`/`abandon` 自动提交一次，误删可 `git` 恢复：
- 结论流水：`<seat>.jsonl`（append-only 事件日志，0-Token 脚本预筛与 DS 审核结论的唯一正本）
- 任务事实链：`history/current.jsonl` 与历史分卷；`tasks/<TASK_ID>.json` 仅为可迁移的旧格式。
- 一根配置：`config.json`（审核席位 / 体检适配器 / 防膨胀闸 / 49 条策略开关，一眼看清开了什么）

---

## 票据文件包与独立审核

票据文件包放在 `<AG_HOME>/projects/<key>/draft/`：`ticket.md` 给人看，`spec.json` 给机器看，`checks/` 放开票前写好的 Python 检查及辅助文件。enroll 生成起步模板；`origin.user_words` 默认为空，必须按用户原话填写后才可 start。

`ticket.md` 必须有四个非空段落：`## 要做成什么`、`## 怎样算做成`、`## 不做什么`、`## 需要你拍板的事`，最后一段可写“无”。不再把机器结果或检查藏在人话标记行中。

start 校验、把 draft 逐字节封存到 `tickets/<task_id>/`，在尚未解冻的 source_head 工地中运行封存检查，cwd 为工地，每条用 Python 执行且限时 300 秒。target 基线必须失败，guard 必须通过，再把完整人话、spec、检查源码和基线交给独立 ticket 席位。seal.json 原子写入，记录全部文件摘要、身份、基线和审核回执。

每张票仍须用户本人 confirm-map，AI 不得代调；实际解冻并返回 ready 后才可施工。verify 运行封存检查、工地 `.ag-check/check_*.py` 追加检查及项目登记命令，并调用 switch；finish 复核 seal、候选和审核后快进合入。封存 ticket.md 不回写现场段，现场由 status/delivery 展示。

确认前或确认后需要改票，都修改 draft/ 后执行 start；status/delivery 的 `revise-ticket-and-start` 提示走这条路径。先校验新包，在 source_head 的干净副本上跑基线并准备新封存；全部成功才冻结现有工地，把旧包移到 `tickets/<task_id>.revisions/<时间戳>/`，换上新包并重新审票。工地代码保留，旧确认和旧验货作废，用户必须再次 confirm-map 后重新 verify。格式、基线或送审前失败保持原封存、确认和权限，不增加修订；审票拒绝则保留已提交的新包，工地冻结，可继续改 draft/ 再 start。未改 draft 的 start 只恢复现场，不重审、不产生修订。不要直接改封存区。

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
| `legacy-ticket-format` | 旧活动票没有封存包时仅支持关闭：使用 abandon；后续使用 draft/ 文件包。 |

## 审核配置（项目 `config.json` 的 `critic` 段）

通过以下命令生成或查看当前配置状态与标准模板（AI 会自动读取其中的 `config_guide` 指导用户完成配置）：

```powershell
python -m ag config <PROJECT_ROOT>
```

配置支持**全局级** `<AG_HOME>/critic.json` 与**项目级** `<AG_HOME>/projects/<PROJECT_KEY>/config.json` 的 `critic` 段；项目级覆盖全局：项目 `config.json` 没有 `critic` 段时继承全局配置（升级不会再写入默认段）；只要有 `critic` 段（哪怕只写 `{"enabled": false}`），就由项目段覆盖全局。旧项目级 `critic.json` 仅作兼容读取。API Key 存放在环境变量中，切勿写入 JSON：

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

在已有有效本人授权、且实际 `ready` 的活跃工作树中，可创建最多 3 个与厂商无关的 Worker 任务档案：

```powershell
python -m ag worker-create <PROJECT_ROOT> --portrait "做成之后：..." --anchor "保持原有鉴权行为不变" --hard-anchor "严禁运行 ag finish" --write-allow src/auth --write-allow src/core
```

- Worker 命令守卫只用于防误操作；它不是文件系统沙箱，不能约束不可信进程或替代真实验收。
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
  - `lift-4` / `lift-11`：运行 `AG_LIFT_CMD`（经 shell），输出按 UTF-8 解码；超过 `AG_LIFT_TIMEOUT` 秒（1 到 1800 的整数，不设置或非法时为 300）就结束整个进程树，该条 finding 标 `timed_out=true`，`ag lift` 照常返回。`lift-2` 的 linter 同样受此超时约束。
  - `lift-12`：意图锚点注意力跟踪。
  - `lift-13` / `lift-14`：变更感知摘要与任务快照。
  - `lift-15`（红线回声）：对比上一票与本票红线，提醒被删减的旧红线。
  - `lift-16`（捷径嗅探）：扫描新增代码中的吞异常、引 mock、占位符等应试假实现信号。
  - `lift-17`（可拔除建议）：检测新增子模块的跨文件引用触点数，引导单点挂载。
  -。
- **`see`（客观观测）**：
  - `see-10` / `see-11`：重复样式症状与所有权归属透视。
  - `see-12`（强推与反向引用）：统计跨语言类型/Lint 压制符净增与反向 import。
  - `see-13`（考卷净荷与防抖）：观测实时日志体积、红线封存状态与 `.ag-check` 大文件过滤。
  - `see-14`（票据与红线轨迹）：汇总项目 `history/` 分卷与兼容旧票档，展示高频红线分布及同票交付事实。
  - `see-15`（一前一后精简考卷）：记录单次 `switch` 与窗口裁剪节省的字符与 Token 账本。
  - `see-17`（评审跑没跑）：现算开票审 / 批改 / 开关三席各跑过多少次、通过 / 拒绝 / 没审各多少、没审的原因与次数，以及每席最近一条结论与时间。
  - `see-18`（正本对账）：把评审历史的正本 jsonl 与 `-last.json` 缓存逐字段对上，报出不一致字段、坏行数，以及旧 `ag.sqlite` 里还剩多少行镜像。


## 单票与旧数据

每张票独立审票，由用户本人执行 `confirm-map`，实际解冻并返回 `ready` 后才可施工。`continuation_of` 仅携带前票共同目标、贡献与未完成项作参考，不传递授权。

修改已确认的票时，按 `revise-ticket-and-start` 编辑 draft/ 并运行 start；同票重审后由用户再次 confirm-map，然后重新 verify。

遇到 `long-ticket-retired` 时用 `abandon` 关闭活动票。旧长票数据原样留在 `<AG_HOME>`，不迁移；新代码不读取、不改写、不删除旧 `long/`、`long-goals.sqlite3` 和历史记录。归档票查询只提供降级视图，不授予权限。

## 真人确认与授权证明

确认只能由用户本人在自己的终端执行。AI 负责展示票包、把 `python -m ag confirm-map <PROJECT_ROOT>` 命令交给用户并等待，不代为执行。自治放行 `approve-self` 同样需要人在场。MCP 的 `ag_confirm_map` 已删除。

先核对原有状态，再在 stderr 展示封存票面四段原文、一行机器摘要和 4 位短码；用户最多输入 3 次，忽略大小写与首尾空白。stdout 只输出 JSON 回执。Windows 仅凭 stdin 的 GetConsoleMode 成功判断真控制台；其他系统要求 os.isatty(0) 和 termios.tcgetattr(0) 均成功。Git Bash/mintty、Windows Terminal 尚未真人实测，若被拒请换用自己的 PowerShell/cmd 窗口，Git Bash 也可尝试 winpty 前缀。

`AG_SYNTHETIC_CONFIRM=1` 仅供测试，且 AG_HOME 的真实路径必须在当前进程 tempfile.gettempdir() 下才生效；合成确认仍打印确认屏，不出短码，记录 synthetic 证明。真实默认 AG_HOME 不接受合成确认。授权必须同时匹配任务布尔值、authorization_identity 和历史确认事件的 proof；合成证明离开临时目录即失效。旧的无证明确认不迁移。

| 拒绝码 | 含义与处理 |
|---|---|
| `human-console-required` | stdin 不是真控制台。把命令交给用户，在用户自己的终端运行。 |
| `human-code-mismatch` | 连续 3 次短码不符，未记录批准；用户核对票面后可重试。 |
| `authorization-unproven` | 缺少同身份的有效证明事件，布尔值不授予权限；人工核对确认来源，不能靠编辑状态解锁。 |

已知边界：本关口防止工具随手代签，不防刻意伪造控制台、注入按键或重写历史。历史 sha256 不带密钥；这些有意绕过留待方案 D，本版不实现个人口令。

## 现场检查与停工

要拉安灯（andon），不要绕路。走不通时主动说明原因是正常协作，不应越过票面范围硬做。

有活动且 ready 的票，每次 CLI 命令或 MCP 工具调用前检查工地；status 也会收回施工权，但从不授予权限。只记录本次 site.changed、out_of_scope、budget 和 reminders，不写施工轨迹（T8）。改动相对 source_head，含未跟踪文件、排除 .ag-check/；deny 优先，allow/docs 支持精确文件名和 ** 跨目录 glob。预算取文件数比例和增删行数比例的较大者：低于 70% 记录，达到 70% 提醒，超过 100% 加重提醒，超过 150% 停工；越界立即停工。

`andon <root> --reason "走不通的原因"` 主动停工。ag 复用冻结机制，记录 site-stopped 事件和 task.site_stop。readiness=stopped、next_action=handoff、hazards 含 site-stopped；verify、finish 和 worker 拒绝施工。abandon、andon、handoff、backbrief、confirm-map 不触发现场检查。

停工后有两条路：① `handoff <root>` 生成客观简报，保存在 tickets/<id>.handoff/，包含原票、结果、改动与越界清单、预算、原因和给新会话的提示词；建议交给新会话。接手会话写 JSON `{ "out_of_scope": ["实际越界文件"], "goal": "至少二十字的目标复述", "next": "处理计划" }`，用 `backbrief <root> --file <json>` 回述。清单必须与现场完全一致，goal 至少 20 字，next 非空，否则 backbrief-mismatch 并保持冻结。通过后仍先核对 T5 既有授权证明，才解冻并记录 site-resumed；AI 可以执行 backbrief，但不能借此取得新授权。越界或超预算未解决，下一次调用仍会再次停工。② 修改 draft/ 后 start，重新审票，由用户本人 confirm-map；确认成功清除 site_stop，保留已有代码。

MCP 提供 ag_andon、ag_handoff、ag_backbrief。没有调用 ag 就不会触发检查，这是已知局限；verify 前一定检查。不能通过改状态、改封存或绕过 T5 解锁。遇到 `site-stopped` 先交接；遇到 `backbrief-mismatch` 按客观事实修正回述。
