# AutoGovern：AI 施工入口

ag 是本地交付护栏与独立审核底座。主仓 `<PROJECT_ROOT>` 在活动票期间冻结；只有 `<WORKTREE>` 可施工。ship 设置 product 或拒绝交付，lift/see 只给建议和观测。

票据文件包放在 `<AG_HOME>/projects/<key>/draft/`：`ticket.md` 给人看，`spec.json` 给机器看，`checks/` 放开票前写好的 Python 检查及辅助文件。enroll 生成起步模板；`origin.user_words` 默认为空，必须按用户原话填写后才可 start。

`ticket.md` 必须有四个非空段落：`## 要做成什么`、`## 怎样算做成`、`## 不做什么`、`## 需要你拍板的事`，最后一段可写“无”。不再把机器结果或检查藏在人话标记行中。

start 校验、把 draft 逐字节封存到 `tickets/<task_id>/`，在尚未解冻的 source_head 工地中运行封存检查，cwd 为工地，每条用 Python 执行且限时 300 秒。target 基线必须失败，guard 必须通过，再把完整人话、spec、检查源码和基线交给独立 ticket 席位。seal.json 原子写入，记录全部文件摘要、身份、基线和审核回执。

每张票仍须用户本人 confirm-map，AI 不得代调；实际解冻并返回 ready 后才可施工。verify 运行封存检查、工地 `.ag-check/check_*.py` 追加检查及项目登记命令，并调用 switch；finish 复核 seal、候选和审核后快进合入。封存 ticket.md 不回写现场段，现场由 status/delivery 展示。

确认前或确认后需要改票，都修改 draft/ 后执行 start；status/delivery 的 `revise-ticket-and-start` 提示走这条路径。先校验新包，在 source_head 的干净副本上跑基线并准备新封存；全部成功才冻结现有工地，把旧包移到 `tickets/<task_id>.revisions/<时间戳>/`，换上新包并重新审票。工地代码保留，旧确认和旧验货作废，用户必须再次 confirm-map 后重新 verify。格式、基线或送审前失败保持原封存、确认和权限，不增加修订；审票拒绝则保留已提交的新包，工地冻结，可继续改 draft/ 再 start。未改 draft 的 start 只恢复现场，不重审、不产生修订。不要直接改封存区。

## 操作纪律

- 开始或恢复前先读用户合同、红线、delivery 和适用技能；不能缩小承诺。
- 不代用户 confirm-map，不手改批准状态或 ACL，不在主仓施工或提交。
- 未 ready 不修改产品；工地不可写时报告真实原因，不绕过冻结。
- 每条结果对应真实 target，保护已有行为用 guard；只在工地 .ag-check/ 追加检查，不建立常驻 tests/ 答案库。
- 自检走不通真实内部入口时查明断点，不用造假桩掩盖。
- 完成后运行 verify，引用 task_id、verified_tree、switch.report_id 和检查结果；失败按具体证据修复。
- 审核配置通过 config/config_guide 诊断；只检查密钥环境变量是否存在，不索要或打印密钥。
- history-corrupt 报出的文件和行号交人工核对，不自动改写历史；旧长票数据不迁移，long-ticket-retired 用 abandon。

## 导航

[写包 ag-anchor](skills/ag-anchor/SKILL.md) · [工作流 ag-guide](skills/ag-guide/SKILL.md) · [配置 ag-config](skills/ag-config/SKILL.md) · [排障 ag-troubleshooting](skills/ag-troubleshooting/SKILL.md)

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

有活动且 ready 的票，每次 CLI 命令或 MCP 工具调用前检查工地；status 也会收回施工权，但从不授予权限。记录本次 site.changed、out_of_scope、budget 和 reminders，并保留产品树变化的施工轨迹。改动相对 source_head，含未跟踪文件、排除 .ag-check/；deny 优先，allow/docs 支持精确文件名和 ** 跨目录 glob。预算取文件数比例和增删行数比例的较大者：低于 70% 记录，达到 70% 提醒，超过 100% 加重提醒，超过 150% 停工；越界立即停工。

`andon <root> --reason "走不通的原因"` 主动停工。ag 复用冻结机制，记录 site-stopped 事件和 task.site_stop。readiness=stopped、next_action=handoff、hazards 含 site-stopped；verify、finish 和 worker 拒绝施工。abandon、andon、handoff、backbrief、confirm-map 不触发现场检查。

停工后有两条路：① `handoff <root>` 生成客观简报，保存在 tickets/<id>.handoff/，包含原票、结果、改动与越界清单、预算、原因和给新会话的提示词；建议交给新会话。接手会话写 JSON `{ "out_of_scope": ["实际越界文件"], "goal": "至少二十字的目标复述", "next": "处理计划" }`，用 `backbrief <root> --file <json>` 回述。清单必须与现场完全一致，goal 至少 20 字，next 非空，否则 backbrief-mismatch 并保持冻结。通过后仍先核对 T5 既有授权证明，才解冻并记录 site-resumed；AI 可以执行 backbrief，但不能借此取得新授权。越界或超预算未解决，下一次调用仍会再次停工。② 修改 draft/ 后 start，重新审票，由用户本人 confirm-map；确认成功清除 site_stop，保留已有代码。

MCP 提供 ag_andon、ag_handoff、ag_backbrief。没有调用 ag 就不会触发检查，这是已知局限；verify 前一定检查。不能通过改状态、改封存或绕过 T5 解锁。遇到 `site-stopped` 先交接；遇到 `backbrief-mismatch` 按客观事实修正回述。

## 工地轨迹与多余物

现场检查之后及 verify 开始时，在 `<AG_HOME>/projects/<key>/tickets/<id>.trail.jsonl` 追加产品快照，关票后保留。记录时间、命令、产品树、各文件增删行数，包含未跟踪产品文件、排除 `.ag-check`；产品树未变不追加。只在调用 ag 时观察，两次调用之间的中间过程看不到。使用临时 index，不动真实暂存区，快照不进入 history。

终审收到 `trajectory`：快照数、时间跨度、各文件改写次数与首次出现序号、建了又删和越界后撤回的文件、停工次数；轨迹只作参考，单独不构成拒绝理由。`extraneous` 列出新增文件、按适配器引用规则判定的无人引用新增源文件，以及像草稿的名称。终审会审查多余物：每个新增文件和新增函数必须说明服务于 `spec.results` 哪一条，新增文件须有出处，无法说明就判 fail。原有审核和 T7 停工规则继续适用，走不通要拉安灯，不要绕路。

## 上下文观测

`context_burden` 只观测、不拦截：开票按 source_head 上 allow 减 deny 的已跟踪文件，加结构适配器 ref_patterns 规则的一跳直接引用估算（未配置时沿用终审 neighbors），随票保存，在审票、status、delivery 展示。est_tokens 按下述 chars_per_token 实测比率向上取整，空输入为零；这是粗估，不设阈值，不要求拆票。

审核历史 payload 的 `usage` 记录 prompt_tokens、completion_tokens、total_tokens、cached_tokens、calls 和 per_call 各次调用；支持流式尾块和普通 JSON，缺失或异常为 null，不影响结论，不改请求参数。终审 `exam_size` 记录实际 system/user 的 sent_chars、补回被省略文件/检查/diff 原文的 raw_chars、truncated_files。verify 的 context 对照开票 estimate、measured 的 usage/exam_size 与按实际改动重算的 actual_scope。`context_trend` 从历史展示最近十次终审，新的在前，旧记录缺值为 null。不新增 hazard、门禁或审核维度，不改截断规则。

## 熵账与减重参照

`entropy` 对比候选与 source_head，统计产品增删及净增行、新文件、捷径、抑制标记增减、宽泛异常、平行实现名称、同名文件；含未跟踪文件，排除 `.ag-check`。复用 advice 规则，每类证据 items 最多 10 条，同一份熵账进入终审考卷、verify 输出与终审历史。`entropy_trend` 展示最近 10 次终审，旧记录缺值为 null。`budget_actual` 复用 T7 现场预算算法；`budget_reference` 按每票最新终审展示最近 10 张票的 kind、预算、实际量和比例。

`slim_reminder` 从 finish 历史统计上次 slim 合入后的非减重票，满 8 张或累计产品净增 800 行时提示下一张宜开减重票；放弃的票不计，slim 合入后清零，没有 slim 时从最早票包格式票开始。不进入 hazards，不改变 readiness、next_action，不新增拒绝或审核维度；熵账和预算均只作参考。

`chars_per_token` 取最近 10 条有效终审 sent_chars/prompt_tokens 的中位数，ratio_source 为 history；没有实测则为 default、4.0。开票 context_burden 和 actual_scope 都按 ceil(total_chars / chars_per_token) 粗估，context_burden 只观测、不拦截；已保存的开票估算保留当时比率。

## 修复票根因

仅 `kind=fix` 必须填写 `root_cause`，去掉首尾空白后至少 20 个字符，否则报 `spec-invalid` 并点名字段。根因要说明哪里、为什么会出错，不能只复述症状。审票将症状式说明写入 doubts，并在 goal_clarity 上判 fail；终审考卷顶层保留 root_cause 原文，逐个核对改动是解决根因，还是只在症状处加判断、兜底或特例，后者判 fail 并提供改动的 path:line。feature、slim 不受此要求影响，其他审核规则不变。

## 检查毕业与撤销

sealed_check 观测的 timeout_s 与命令探针规则相同：须为 1 到 1800 的整数，默认 300 秒；非法值判红且不执行脚本。

在 spec.json 预注册 `graduate: [{"file": "checks/check_x.py"}]`，仅允许 target；可选 task 指向已经合入票的 target，可选 area 是非空相对 glob 列表，默认用来源票 scope.allow。补毕业的旧票检查会先在本票 verify 中运行；毕业守护只保护行为，不计入新票的完成证明。

合入成功后登记 grad-<来源票号>-<检查名>（最长 64 字符）及审计，直接引用封存原件。sealed_check 每次先按 seal.json 核对 checks/ 全部文件和辅助模块（忽略 __pycache__）；篡改、缺失、多出文件都报 guard-tampered，脚本不执行。核对通过后用 Python -B 在被测树执行。area 用 site.matches，支持 * 和 **；毕业守护永不自动归档，普通探针保持原规则。

只能在票包声明 `retires: [{"id": "grad-...", "reason": "至少二十个字符的撤销理由"}]` 撤销：verify 跳过并返回 retired_guards，合入后才删除并审计；放弃不登记、不删除。直接 ag probe drop 会报 guard-graduated。status.guard_cost 汇总毕业守护最近耗时，达到 600 秒提示用 retires 开票精简，只提示，不进 hazards、不改 readiness 或 next_action。不复制脚本，不新增 guards_dir 配置。
