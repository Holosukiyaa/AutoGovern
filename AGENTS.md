# AutoGovern：AI 施工入口

ag 是本地交付护栏与独立审核底座。主仓 `<PROJECT_ROOT>` 在活动票期间冻结；只有 `<WORKTREE>` 可施工。ship 设置 product 或拒绝交付，lift/see 只给建议和观测。

票据文件包放在 `<AG_HOME>/projects/<key>/draft/`：`ticket.md` 给人看，`spec.json` 给机器看，`checks/` 放开票前写好的 Python 检查及辅助文件。enroll 生成起步模板；`origin.user_words` 默认为空，必须按用户原话填写后才可 start。

`ticket.md` 必须有四个非空段落：`## 要做成什么`、`## 怎样算做成`、`## 不做什么`、`## 需要你拍板的事`，最后一段可写“无”。不再把机器结果或检查藏在人话标记行中。

start 校验、把 draft 逐字节封存到 `tickets/<task_id>/`，在尚未解冻的 source_head 工地中运行封存检查，cwd 为工地，每条用 Python 执行且限时 300 秒。target 基线必须失败，guard 必须通过，再把完整人话、spec、检查源码和基线交给独立 ticket 席位。seal.json 原子写入，记录全部文件摘要、身份、基线和审核回执。

每张票仍须用户本人 confirm-map，AI 不得代调；实际解冻并返回 ready 后才可施工。verify 运行封存检查、工地 `.ag-check/check_*.py` 追加检查及项目登记命令，并调用 switch；finish 复核 seal、候选和审核后快进合入。封存 ticket.md 不回写现场段，现场由 status/delivery 展示。

确认前修改 draft 再 start，在同一 task_id 重封存、重跑基线并重新审票；没有改动只恢复现场。确认后改票属于 T4b，本版先 abandon（候选保留在 `refs/ag/abandoned/<task_id>`）再重新开票。不要直接改封存区。

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
| `legacy-ticket-format` | 旧活动票没有封存包，只能 abandon 关闭后用 draft/ 重新开票。 |
