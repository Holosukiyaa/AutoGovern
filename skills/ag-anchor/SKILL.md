---
name: ag-anchor
description: >
  Use before ag_start or during any ag-governed delivery task when the user's
  request needs to be distilled into an observable done-state, positive and
  negative/boundary behavior-chain anchors (anchor:), and narrow focused red
  lines (## 红线) in <AG_HOME>/projects/<key>/ticket.md. Also use when the user says
  锚点, 意图锚点, route, ticket.md, or when a later suggestion drifts from an
  existing anchor.
---

# `ag-anchor`：意图锚点提取与 `<AG_HOME>/projects/<key>/ticket.md` 编写规范

意图锚点（Intent Anchors）用于把用户一句话需求背后隐含的完整业务路线显式化，而不是把它变成死板的步骤清单。`ag` 将意图锚点与红线持久化在任务状态中，AI 必须在开票前、施工中和交卷验货前始终对齐锚点。

## 保持完整交付主线

恢复工作先读 `python -m ag delivery <PROJECT_ROOT> --task-id <TASK_ID>`（MCP：`ag_delivery`）。以 `goal` 和 `remaining` 对齐结果，再根据 `blockers`、`advisories`、`next_action` 继续。读取、开始某步、移动注意力或验证失败都不算已完成；`progress.verified` 必须关联本票报告、候选和实际检查。

完整功能可以跨必要模块并在一票内分阶段实现。普通路线调整说明原因即可，可用 `ag route <PROJECT_ROOT> --reason "原因"` 留痕；减少承诺或冲突硬边界须用 `--requires-decision` 保留待用户决定状态，不能自行缩小目标。真正独立交付的后续工作才用 `ag start --continuation-of <TASK_ID> --contribution "当前贡献"`，携带共同目标与未完成结果；不会自动把所有票连成一条主线。

票面只在 `<AG_HOME>/projects/<key>/ticket.md`。向用户展示完整预览后，由用户亲自执行 `python -m ag confirm-map <PROJECT_ROOT>`；AI 不得代调 CLI 或 MCP。确认报出 `ready` 才代表权限实际恢复，已批准但冻结或解冻失败时继续排障，不开始施工。项目累计票数不提高审查强度；常设条款由可信知识库加载，不能在票面自封来源。

## 关联技能包与路径占位符约定

按职责查阅对应的独立 Skill：
- **项目总入口**：[`AGENTS.md`](../../AGENTS.md)
- **核心概念与 6 步工作流**：[`skills/ag-guide/SKILL.md`](../ag-guide/SKILL.md)
- **独立审核配置与 MCP 挂载**：[`skills/ag-config/SKILL.md`](../ag-config/SKILL.md)
- **常见报错与一键排障手册**：[`skills/ag-troubleshooting/SKILL.md`](../ag-troubleshooting/SKILL.md)

所有说明与命令统一使用动态路径占位符，严禁硬编码个人电脑目录：
- `<PROJECT_ROOT>`：被治理的目标项目仓库根目录（任务进行中处于只读冻结状态）
- `<AG_REPO_ROOT>`：`ag` 仓库根目录（源码运行或安装时使用）
- `<WORKTREE>`：`ag_start` 创建的隔离工作树目录（`<AG_HOME>/worktrees/<PROJECT_KEY>/<TASK_ID>`）
- `<AG_HOME>`：`ag` 状态与配置主目录（默认 `~/.ag`）
- `<PYTHON_EXECUTABLE>`：Python 解释器路径（如 `python`）

---

## 一、开票逆向提炼法（Opening）

1. 仔细阅读用户的真实原话与项目既有规范。
2. 先锁定业务终点，再逆向推演四个要素：
   - **对象（object）**：具体改动哪几个模块、文件或交互表面？
   - **机制（method）**：使用什么真实机制实现？
   - **边界（scope）**：明确包含什么、明确排除什么？
   - **验据（finish）**：什么机器可验证的证据能证明本轮完成？
3. 不要反复向用户讨要“是否可以开始”的许可；合理的默认决策直接放入 `我替你定的`。
4. 将提炼出的意图写入 `<AG_HOME>/projects/<key>/ticket.md` 及 `ag_start` 的 `portrait`：
   - `anchor: <带正反向完整行为链路的软锚点>`
   - `anchor!: <仅当源自用户或项目明确硬规则时使用的硬锚点>`
5. 硬锚点（`anchor!:`）绝不能由 AI 凭空猜测生成；AI 可以建议升级，但必须标明来源。
6. 若上述四个要素存在无法靠代码上下文确定的阻塞性未知项，停下来只问一个精炼的问题，严禁盲目脑补施工。

---

## 二、高质量 `<AG_HOME>/projects/<key>/ticket.md` 编写规范

`<AG_HOME>/projects/<key>/ticket.md` 是唯一权威意图文档，缺失或未填写有效内容时 `ag_start` 会直接拒绝。

### 标准模板

```markdown
# 票

## 意图
做成之后：用大白话写清楚这轮改动完成后，用户或系统能观察到的真实结果（明确改什么对象、用什么机制、包含与排除什么边界，不少于 30 字）。

anchor: 在哪几个具体模块或文件中建立什么机制：当满足什么正常条件时产生什么预期结果，若遇到什么异常或违规边界则如何拦截或拒绝
anchor: 在哪个交互或数据链路上收敛什么行为：当输入或状态变化时如何流转，若出现越界或缺失则如何兜底保护

## 红线
- 针对本票目标的具体禁令 1：明确指出不能破坏的接口契约、不能触碰的目录或严禁引入的做法。
- 针对本票目标的具体禁令 2：聚焦本次改动的真实高风险边界（3~5 条即可，严禁写“代码要规范”“不能有 bug”等空泛套话）。
```

### 三大审票高分铁律（决定 `ticket` 席位能否一次通过）

1. **`## 意图` 大白话讲清可观测完成态**：
   - 必须包含以 `做成之后：`（或 `固定:`）开头的完整描述，直白说明交付后用户或机器能看到什么变化，不要堆砌空洞口号。
   - `## 意图` 一旦确认即保持原样锁定；后续 `ag_status`、`ag_verify`、`ag_finish` 只会更新 `## 现场`。
2. **`anchor:` 必须具备正反完整行为链路**：
   - 每条 `anchor:` 必须是不少于 20~25 字的带动词陈述句。
   - 必须同时写清：**具体作用对象 + 正向路径（`当……时……`）+ 反向/异常/边界拦截（`若……则……`）**。
   - 严禁把锚点缩写成“提升稳定性”“确保安全”之类的空泛口号。
   - 软锚点数量控制在精炼范围内（若达到 9 条或以上应主动合并收敛）。
3. **`## 红线` 窄化聚焦、拒绝套话与照抄**：
   - 只写与本票改动强相关的 3~5 条具体硬边界（如禁止触碰某模块、禁止引入非标准库、禁止出现硬编码个人路径等）。
   - 严禁写“代码要整洁”“保证没有 bug”等空泛套话；重复的本票条款须核对是否与当前改动相关。可信常设条款由程序单独标注来源，完整封存并继续约束施工，不计入本票聚焦度和跨票重复率，不能为了减少重复而删掉义务。
   - 开工时，`## 红线` 与硬锚点（`anchor!:`）会被自动封存写入 `<AG_HOME>/projects/<key>/redlines.copy`。

### 完整功能与验据的边界

- 以共同输入输出、全部完成条件和反向边界定义一项代码功能，允许必要跨模块接线与内部施工阶段；分阶段不代表可以部分交付，不必为了审票机械拆成单一函数或代码片段。
- 真实入口、端到端场景、迁移演练和性能测量属于代码验据。若只生产指定业务内容、操作已有流程、拼接无关目标或缺少完成条件，仍需拒绝；“完整功能”以及“只改/仅建某段”等措辞均不是过票口令。
- 常设条款只来自 `<AG_HOME>/projects/<key>/knowledge/redlines.md` 的 `## 常设红线` 区；历史日期段与票面自称常设不改变来源。审票同时接收完整 `redlines`、`standing_redlines` 与 `ticket_redlines`；本票条款为空仍不能通过，已有来源读取失败须显式报错，不能退回空集掩盖。

### 审票打回（`rejected`）原地重审机制

若 `ag_start` 返回 `ticket_review.outcome == "rejected"`（无论是 `script-prescreen-rejected` 还是 `ticket-review-rejected`）：
- 查看 `ticket_review.reasons`、`suggestions`、`doubts` 以及 `script_digest.hard_failures`。
- **无需执行 `ag_abandon`**：在尚未 `confirm-map` 前，直接编辑 `<AG_HOME>/projects/<key>/ticket.md` 补齐正反向链路、聚焦红线并回答 `doubts`，然后**直接重新运行 `ag_start`** 即可原地更新 `<AG_HOME>/projects/<key>/redlines.copy` 并开启新一轮无状态审票。

---

## 三、强制意图图确认门禁（Mandatory `confirm-map` Gate）

`ag_start` 执行成功（且 `ticket_review` 通过或未启用）后，**AI 必须立即停手**：
1. 将返回的 `anchor_preview` 完整展示给用户，并附上 `<AG_HOME>/projects/<key>/ticket.md` 的路径（`anchor_preview_path`）。
2. 等待用户审阅并在终端执行：
   ```powershell
   python -m ag confirm-map <PROJECT_ROOT>
   ```
3. **铁律**：`confirm-map` 代表人类的显式授权，**AI 严禁自行调用 `confirm-map`**。在用户未执行 `confirm-map` 解冻 `<WORKTREE>` 之前，严禁创建 Worker 或修改任何代码。

---

## 四、施工期间的锚点纪律与交付守则

- **隔离施工**：所有代码修改严格在 `<WORKTREE>` 中完成，绝不触碰只读冻结的 `<PROJECT_ROOT>`。
- **一次性自检**：在 `<WORKTREE>/.ag-check/` 下编写验证本票锚点与红线边界的自检脚本（合入时随 `<WORKTREE>` 自动销毁，严禁建立常驻 `tests/`）。
- **自检走不通真实入口的处置**：写自检时若发现「本可以走真实入口、却只能靠造假桩或手塞假对象才能测」，**这本身就是停止信号，不是省事的捷径**。此时正确动作只有两个——
  - 停下来找用户拍板，说明走不通的真实入口在哪、为什么只能造假；
  - 或被 `switch` 终审拦下后回来面对这个断点。
  - **严禁默默造假、绕过真实入口、当没事发生**：造假桩过自检是在给上游断点打掩护，断点会埋到后续票才爆。
  - 分辨两类桩：**合理的桩**只有「真外部依赖边界」（如 AI 对话这类本就没真件可连的外部边界）；**警报的桩**是「本可走真件却走不通」（如手塞一个假会话对象），其根因多半是上游真实入口本身坏了——先查上游入口，再决定要不要桩。
- **锚点对齐与偏移披露**：
  - 在编辑文件前、切换实现方向前重新阅读锚点。
  - 若实现方式偏离了软锚点（`anchor:`），可以继续推进，但必须向用户明确披露偏离原因。
  - 若实现方式与硬锚点（`anchor!:`）或 `## 红线` 冲突，必须先停下说明冲突，询问用户是否放弃当前票重开（`ag_abandon`）。
  - 严禁静默篡改或删除已锁定的锚点。
- **Worker 协同与验货**：
  - 如需拆分任务，仅使用 `python -m ag worker-create <PROJECT_ROOT> ...` 创建（最多 3 个 Worker），并将 `anchor_preview`、`<AG_HOME>/projects/<key>/ticket.md` 与对应锚点传入 Worker 提示词。
  - 完工后必须运行 `ag_verify` 接受机器与 `switch` 终审，严禁口头自证通过。
