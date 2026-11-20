---
name: ag-guide
description: Explain AG delivery lanes, ticket packages and the six-step workflow.
---

# AG 交付工作流

ag 用主仓冻结、隔离工地和独立审核约束 AI 施工。ship 决定交付与门禁；lift 给建议；see 给事实，两条建议轨道不能拦 finish。

票据文件包放在 `<AG_HOME>/projects/<key>/draft/`：`ticket.md` 给人看，`spec.json` 给机器看，`checks/` 放开票前写好的 Python 检查及辅助文件。enroll 生成起步模板；`origin.user_words` 默认为空，必须按用户原话填写后才可 start。

`ticket.md` 必须有四个非空段落：`## 要做成什么`、`## 怎样算做成`、`## 不做什么`、`## 需要你拍板的事`，最后一段可写“无”。不再把机器结果或检查藏在人话标记行中。

start 校验、把 draft 逐字节封存到 `tickets/<task_id>/`，在尚未解冻的 source_head 工地中运行封存检查，cwd 为工地，每条用 Python 执行且限时 300 秒。target 基线必须失败，guard 必须通过，再把完整人话、spec、检查源码和基线交给独立 ticket 席位。seal.json 原子写入，记录全部文件摘要、身份、基线和审核回执。

每张票仍须用户本人 confirm-map，AI 不得代调；实际解冻并返回 ready 后才可施工。verify 运行封存检查、工地 `.ag-check/check_*.py` 追加检查及项目登记命令，并调用 switch；finish 复核 seal、候选和审核后快进合入。封存 ticket.md 不回写现场段，现场由 status/delivery 展示。

确认前或确认后需要改票，都修改 draft/ 后执行 start；status/delivery 的 `revise-ticket-and-start` 提示走这条路径。先校验新包，在 source_head 的干净副本上跑基线并准备新封存；全部成功才冻结现有工地，把旧包移到 `tickets/<task_id>.revisions/<时间戳>/`，换上新包并重新审票。工地代码保留，旧确认和旧验货作废，用户必须再次 confirm-map 后重新 verify。格式、基线或送审前失败保持原封存、确认和权限，不增加修订；审票拒绝则保留已提交的新包，工地冻结，可继续改 draft/ 再 start。未改 draft 的 start 只恢复现场，不重审、不产生修订。不要直接改封存区。

## 六步交付

1. 登记：运行 `python -m ag enroll <PROJECT_ROOT>`，配置 Git 钩子并在 ag 家里生成 draft/ 模板。
2. 写包：按 ag-anchor 技能填写四段 ticket.md、spec.json、target/guard 检查，先对齐所有完成条件和拒绝边界。
3. 开票：运行 `python -m ag start <PROJECT_ROOT>`，接受格式校验、基线和独立审票。失败按具体证据修正；确认前可原地重审。
4. 本人确认：展示封存 ticket.md、spec 和检查基线及审核回执。由用户亲自 `confirm-map`，AI 不代调；ready 才能写工地。
5. 施工验货：只改 `<WORKTREE>`，追加检查写 .ag-check/，完成全部结果后 `verify`，机器检查、探针及单次 switch 都要通过。
6. 收尾：核对完整交付结果后按用户授权 `finish`；弃票 `abandon` 会保留候选引用并清理工地、解冻主仓。

恢复工作先运行 `delivery --task-id <TASK_ID>`：核对完整目标、已验证项、remaining、blockers 与 next_action；查询不授予权限，失败与开始执行都不算完成。新事实写入可校验历史，坏行由人工核对，不能为解锁删历史。

独立审核配置见 [ag-config](../ag-config/SKILL.md)，排障见 [ag-troubleshooting](../ag-troubleshooting/SKILL.md)，写包细则见 [ag-anchor](../ag-anchor/SKILL.md)。

## 常见拒绝

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
