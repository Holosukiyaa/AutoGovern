---
name: ag-anchor
description: >
  Write an AG ticket package in draft/: human ticket.md, machine spec.json,
  target and guard checks, result coverage and opening baselines.
---

# 怎么写票据文件包

票据文件包放在 `<AG_HOME>/projects/<key>/draft/`：`ticket.md` 给人看，`spec.json` 给机器看，`checks/` 放开票前写好的 Python 检查及辅助文件。enroll 生成起步模板；`origin.user_words` 默认为空，必须按用户原话填写后才可 start。

`ticket.md` 必须有四个非空段落：`## 要做成什么`、`## 怎样算做成`、`## 不做什么`、`## 需要你拍板的事`，最后一段可写“无”。不再把机器结果或检查藏在人话标记行中。

start 校验、把 draft 逐字节封存到 `tickets/<task_id>/`，在尚未解冻的 source_head 工地中运行封存检查，cwd 为工地，每条用 Python 执行且限时 300 秒。target 基线必须失败，guard 必须通过，再把完整人话、spec、检查源码和基线交给独立 ticket 席位。seal.json 原子写入，记录全部文件摘要、身份、基线和审核回执。

每张票仍须用户本人 confirm-map，AI 不得代调；实际解冻并返回 ready 后才可施工。verify 运行封存检查、工地 `.ag-check/check_*.py` 追加检查及项目登记命令，并调用 switch；finish 复核 seal、候选和审核后快进合入。封存 ticket.md 不回写现场段，现场由 status/delivery 展示。

确认前或确认后需要改票，都修改 draft/ 后执行 start；status/delivery 的 `revise-ticket-and-start` 提示走这条路径。先校验新包，在 source_head 的干净副本上跑基线并准备新封存；全部成功才冻结现有工地，把旧包移到 `tickets/<task_id>.revisions/<时间戳>/`，换上新包并重新审票。工地代码保留，旧确认和旧验货作废，用户必须再次 confirm-map 后重新 verify。格式、基线或送审前失败保持原封存、确认和权限，不增加修订；审票拒绝则保留已提交的新包，工地冻结，可继续改 draft/ 再 start。未改 draft 的 start 只恢复现场，不重审、不产生修订。不要直接改封存区。

## 从用户原话到结果与检查

先读完整用户请求和项目边界，在人话票中写清可观察的完成态、验收方式、排除范围和待决定事项。真实代码功能可跨必要模块，运行与端到端场景可以是验据；不要机械拆碎一项功能，也不要把“启动过”当完成。

spec 与人话必须一致，机器部分只能更细，不能偷偷删掉承诺。字段如下：

- `schema` 固定为 `ag.ticket.v2`。
- `kind` 是 feature、fix 或 slim；fix 的 `root_cause` 去掉首尾空白后至少 20 个字符，feature、slim 不要求。
- `origin.user_words` 是非空的用户原话列表，`origin.source` 写来源和日期。
- `results` 非空，每项 id 唯一，text 至少 20 字，写触发条件、正向结果和拒绝边界。内部 soft 锚点按原顺序由它生成。
- `scope.allow` 为非空相对路径模式列表，deny/docs 也是路径模式列表；不允许绝对路径或上级越界。
- `redlines` 每项 text 写具体边界，source 只能是 user、standard、ticket。来源不可臆造；内部红线由这些 text 生成。
- `budget.files`、`budget.lines` 是正整数。T4a 只校验格式并交审核判断合理性，实际超范围或超预算停工属于 T7。
- `continuation_of` 可选，只在 spec.json 写，前票必须已关闭且本人确认；共同目标、贡献和未完成项仅作参考。
- `checks` 每项有 file、kind、serves。file 是 checks/ 下真实的 check_*.py，相对路径不能含上级越界，也不能通过链接逃出包。

每条 result 至少有一条 target 检查覆盖；target 的 serves 引用结果 id，guard 可以引用结果或写 ["guard"]。检查覆盖正向与反向边界，不能用桩替代本来能走通的产品入口。真正的外部依赖边界可以隔离；如果被测内部入口走不通，应查明断点，不准制造假通过。

## 修复票根因写法

仅 kind=fix 必填 `root_cause`：至少 20 字，写清“哪里”（模块、函数或具体处理位置）和“为什么”（输入如何触发错误的机制），不能只复述症状。不要为了凑长度把“报错、结果不对”重复几遍。

- **正例**：`greet` 在参数入口直接调用 `name.strip()`，未校验输入类型，传入 None 时先触发 AttributeError，无法按接口约定拒绝非法名字。
- **反例**：`greet` 遇到某些名字总是报错，结果不对，应该加一个判断修好它。这里只写症状，没有指出出错机制与位置。

审票会将仅复述症状的根因写入 doubts，并在 goal_clarity 上判 fail；终审逐项核对改动是否解决 root_cause，不能仅在症状上叠加兜底或特例。

## 基线与审核

target 开票前为红、交卷变绿；guard 开票和交卷均为绿。非零退出可能是导入失败或脚本崩溃，ticket 审票员必须结合源码与 tail 判断红在正确原因上。三维名称和阈值不变：goal_clarity、anchor_chain、redline_focus，任一低于 7 分或 fail 就拒绝。

仅在工地内修改产品；施工期可以在 .ag-check/ 追加检查，不能删改封存检查。verify 后引用 task_id、候选、switch.report_id 和实际验据，不以口头自证替代回执。旧长票数据原样留在 AG_HOME，不迁移；long-ticket-retired 用 abandon 关闭。

## 拒绝码

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

## 检查毕业与撤销

在 spec.json 预注册 `graduate: [{"file": "checks/check_x.py"}]`，仅允许 target；可选 task 指向已经合入票的 target，可选 area 是非空相对 glob 列表，默认用来源票 scope.allow。补毕业的旧票检查会先在本票 verify 中运行；毕业守护只保护行为，不计入新票的完成证明。

合入成功后登记 grad-<来源票号>-<检查名>（最长 64 字符）及审计，直接引用封存原件。sealed_check 每次先按 seal.json 核对 checks/ 全部文件和辅助模块（忽略 __pycache__）；篡改、缺失、多出文件都报 guard-tampered，脚本不执行。核对通过后用 Python -B 在被测树执行。area 用 site.matches，支持 * 和 **；毕业守护永不自动归档，普通探针保持原规则。

只能在票包声明 `retires: [{"id": "grad-...", "reason": "至少二十个字符的撤销理由"}]` 撤销：verify 跳过并返回 retired_guards，合入后才删除并审计；放弃不登记、不删除。直接 ag probe drop 会报 guard-graduated。status.guard_cost 汇总毕业守护最近耗时，达到 600 秒提示用 retires 开票精简，只提示，不进 hazards、不改 readiness 或 next_action。不复制脚本，不新增 guards_dir 配置。
