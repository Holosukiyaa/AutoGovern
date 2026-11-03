---
name: ag-config
description: >
  Use when onboarding a new user or repository, configuring critic.json,
  setting up the independent DS reviewer (ticket and switch seats),
  checking AG_CRITIC_API_KEY environment variables, or mounting ag as an
  MCP server. Guides the user via ag config and onboarding.config_guide
  without ever exposing API key plaintext.
---

# `ag-config`：标准配置文件格式、环境变量与 MCP 挂载

本技能包详细介绍如何通过标准 JSON 配置文件与环境变量配置 `ag` 的独立审核模型（`ticket` 开票审 + `switch` 交卷守门）、如何让 AI 自动诊断配置状态，以及如何在各类 AI 客户端中挂载 `ag` MCP 服务与安装全套自带 Skill。

## 当前接口与职责

日常恢复用 `python -m ag delivery <PROJECT_ROOT> --task-id <TASK_ID>` 或 MCP `ag_delivery` 查看目标、已验证进展、未完成项、阻塞、建议和下一动作。该查询与 `status` 不安装、不迁移、不解冻；完整体检用 `ag_see`，需要生成或修复配置时显式运行 `config/enroll`。

项目配置正本为 `<AG_HOME>/projects/<key>/config.json` 的 `critic` 区，旧 `critic.json` 保持兼容；全局席位仍可从 `<AG_HOME>/critic.json` 读取。`confirm-map` 只读配置并重验审核身份：配置损坏报 `config-error`，审核配置变化报 `intent-identity-changed`，修复并重审后由用户重新确认。API Key 只检查环境变量是否存在，始终不索要、不打印明文。

票面位于 `<AG_HOME>/projects/<key>/ticket.md`，完整展示后用户必须亲自执行 `python -m ag confirm-map <PROJECT_ROOT>`，AI 不得代调 CLI/MCP。进程会即时输出确认阶段，真实解冻成功才 `ready`。新 MCP 同时暴露 `ag_delivery`、`ag_route`；更新软件后重启宿主中的旧 MCP 进程以加载新工具。用 `python -m ag install-skill --target codex` 或 `grok` 同步四套自带技能；安装保留旧版备份。

- **返回项目总入口**：[`AGENTS.md`](../../AGENTS.md)
- **查看 6 步使用流程**：[`skills/ag-guide/SKILL.md`](../ag-guide/SKILL.md)
- **意图锚点与写票规范**：[`skills/ag-anchor/SKILL.md`](../ag-anchor/SKILL.md)
- **遇到报错查排障手册**：[`skills/ag-troubleshooting/SKILL.md`](../ag-troubleshooting/SKILL.md)

---

## 一、路径变量约定

本文档中所有路径均使用动态变量占位符，请根据实际运行环境替换：

- `<PROJECT_ROOT>`：被治理的目标项目仓库根目录
- `<AG_REPO_ROOT>`：`ag` 仓库根目录（若通过源码方式运行）
- `<WORKTREE>`：`ag_start` 创建的隔离工作树目录（`<AG_HOME>/worktrees/<PROJECT_KEY>/<TASK_ID>`）
- `<AG_HOME>`：`ag` 状态与配置主目录（默认 `~/.ag`）
- `<PROJECT_KEY>`：项目登记后生成的唯一标识目录名（如 `<REPO_NAME>-<HASH>`）
- `<PYTHON_EXECUTABLE>`：Python 解释器路径（如 `python`）

---

## 二、让 AI 自动诊断并引导配置（`ag config`）

无需手写配置模板，你可以直接运行以下命令（或让 AI 查看 `ag_status` 返回的 `onboarding.config_guide`）：

```powershell
python -m ag config <PROJECT_ROOT>
```

该命令会输出结构化的 JSON 配置指南，包含：
- `global_config_path`：当前环境的全局配置文件路径（`<AG_HOME>/critic.json`）
- `project_config_path`：当前项目的专属配置文件路径（`<AG_HOME>/projects/<PROJECT_KEY>/config.json`）
- `active_config_path`：当前实际生效的配置文件路径
- `reviewer_ready`：独立审核席位是否已就绪（布尔值）
- `api_key_env` 与 `api_key_present`：所需 API Key 环境变量名及当前是否已设置（仅返回 `true/false` 布尔值，**绝不读取或回显密钥明文**）
- `template` 与 `fields`：可直接复制保存的`critic` 配置段模板与每个字段的中文说明
- `mcp_example`：基于当前 Python 解释器的 MCP 挂载配置示例

---

## 三、配置文件位置与生效优先级

`ag` 采用无弹窗、纯文本的标准 JSON 配置体系，按以下优先级从高到低读取（高优先级自动覆盖低优先级对应项）：

1. **环境变量（最高优先级）**：
   - `AG_CRITIC_ENABLED`（`1` / `true` 开启，`0` / `false` 关闭）
   - `AG_CRITIC_ENDPOINT`（OpenAI 兼容 Chat Completions 接口 URL）
   - `AG_CRITIC_MODEL`（审核模型名称，如 `deepseek-reasoner` 或 `deepseek-chat`）
   - `AG_CRITIC_API_KEY_ENV`（存放 API Key 的环境变量名称，默认 `AG_CRITIC_API_KEY`）
   - `AG_CRITIC_TIMEOUT`（请求超时秒数，默认 `60`）
   - `AG_WORKER_MODEL`（当前施工主力 AI 的模型标识，用于异构模型家族校验）
   - `AG_CRITIC_ALLOW_SAME_FAMILY`（是否允许审核模型与施工模型同家族，`1` / `true` 允许）
2. **项目级配置文件（次高优先级）**：
   - 路径：`<AG_HOME>/projects/<PROJECT_KEY>/config.json`
   - 适用场景：为某个特定仓库单独指定审核模型或开关状态。
3. **全局配置文件（默认推荐）**：
   - 路径：`<AG_HOME>/critic.json`（即 `~/.ag/critic.json`）
   - 适用场景：一次配置，所有登记在 `<AG_HOME>` 下的项目共享同一套独立审核席位配置。

---

## 四、审核配置格式与字段说明

全局 `<AG_HOME>/critic.json` 可直接写入 `template`；项目 `<AG_HOME>/projects/<PROJECT_KEY>/config.json` 应把同样字段放入顶层 `critic` 对象：

```json
{
  "enabled": true,
  "endpoint": "https://api.deepseek.com/v1/chat/completions",
  "model": "deepseek-reasoner",
  "api_key_env": "AG_CRITIC_API_KEY",
  "timeout": 90,
  "worker_model": "",
  "allow_same_family": false
}
```

### 字段详细说明

| 字段名 | 类型 | 默认值 | 详细说明 |
| :--- | :--- | :--- | :--- |
| `enabled` | `boolean` | `false` | 是否启用独立审核席位（同时控制开票 `ticket` 席位与交卷 `switch` 席位）。设为 `true` 后正式生效。 |
| `endpoint` | `string` | `""` | OpenAI 兼容的 Chat Completions 完整接口地址（例如 `https://api.deepseek.com/v1/chat/completions`）。 |
| `model` | `string` | `""` | 独立审核使用的模型名称（例如 `deepseek-reasoner`、`deepseek-chat` 或其他异构推理模型）。 |
| `api_key_env` | `string` | `"AG_CRITIC_API_KEY"` | **存放 API Key 的环境变量名称**（注意：这里填的是环境变量的名字，如 `"AG_CRITIC_API_KEY"` 或 `"DEEPSEEK_API_KEY"`，**严禁在此字段直接填写 `sk-...` 密钥明文！**）。 |
| `timeout` | `number` | `60` | 单次审核 HTTP 请求的超时时间（秒）。若使用推理模型（如 `deepseek-reasoner`），建议设为 `90` ~ `180`。 |
| `worker_model` | `string` | `""` | （可选）声明当前编写代码的施工 AI 模型名称（如 `"gpt-5"`、`"claude-sonnet"`）。用于防止审核模型与施工模型“同家族自己审自己”。 |
| `allow_same_family` | `boolean` | `false` | 当 `model` 与 `worker_model` 属于同一模型家族时，默认会报 `same_family` 并拒绝审核；若确需同家族模型审核，可显式设为 `true`。 |

---

## 五、安全设置 API Key 环境变量

**安全铁律**：永远不要把 API Key 明文写进 `critic.json` 或提交到代码仓库。请通过系统环境变量或 MCP 启动环境注入密钥：

### 方式 1：PowerShell（Windows）
```powershell
# 当前终端会话生效
$env:AG_CRITIC_API_KEY = "<YOUR_API_KEY>"

# 或写入当前用户永久环境变量（设置后需重启终端或 IDE）
[Environment]::SetEnvironmentVariable("AG_CRITIC_API_KEY", "<YOUR_API_KEY>", "User")
```

### 方式 2：Bash / Zsh（macOS / Linux）
```bash
# 写入 ~/.bashrc 或 ~/.zshrc
export AG_CRITIC_API_KEY="<YOUR_API_KEY>"
```

设置完成后，运行 `python -m ag config <PROJECT_ROOT>`，检查返回 JSON 中的 `"api_key_present": true` 即可确认环境变量已就绪。

---

## 六、MCP 客户端挂载配置

你可以将 `ag` 作为标准 stdio MCP Server 挂载到 Codex、Claude Code、Cursor 等支持 MCP 的客户端中。

### 1. 若已通过 `pip install -e <AG_REPO_ROOT>` 安装到 Python 环境：

```json
{
  "mcpServers": {
    "ag": {
      "command": "<PYTHON_EXECUTABLE>",
      "args": ["-m", "ag", "mcp"],
      "env": {
        "AG_HOME": "<AG_HOME>",
        "AG_CRITIC_API_KEY": "<YOUR_API_KEY>"
      }
    }
  }
}
```

### 2. 若直接通过源码目录运行（免安装模式）：

```json
{
  "mcpServers": {
    "ag": {
      "command": "<PYTHON_EXECUTABLE>",
      "args": ["-m", "ag", "mcp"],
      "env": {
        "AG_HOME": "<AG_HOME>",
        "PYTHONPATH": "<AG_REPO_ROOT>/src",
        "AG_CRITIC_API_KEY": "<YOUR_API_KEY>"
      }
    }
  }
}
```

---

## 七、一键安装自带的 4 套独立 Skill

`ag` 在 `skills/` 目录下内置了 4 套职责分明的独立技能包：
- [`skills/ag-anchor/SKILL.md`](../ag-anchor/SKILL.md)：意图锚点提炼、`<AG_HOME>/projects/<key>/ticket.md` 编写与 `confirm-map` 确认纪律
- [`skills/ag-guide/SKILL.md`](../ag-guide/SKILL.md)：项目核心原理、三条正交轨道与 6 步完整工作流
- [`skills/ag-config/SKILL.md`](../ag-config/SKILL.md)：`critic.json` 配置、环境变量与 MCP 挂载指南
- [`skills/ag-troubleshooting/SKILL.md`](../ag-troubleshooting/SKILL.md)：常见报错码与问题排障手册

可通过以下命令将全部 4 个 Skill 一键安装到对应 AI 工具的全局技能目录：

```powershell
# 安装全部 4 个 Skill 到 Codex 技能目录 (~/.codex/skills/{ag-anchor,ag-guide,ag-config,ag-troubleshooting})
python -m ag install-skill --target codex

# 安装全部 4 个 Skill 到 Grok 技能目录 (~/.grok/skills/{ag-anchor,ag-guide,ag-config,ag-troubleshooting})
python -m ag install-skill --target grok
```
