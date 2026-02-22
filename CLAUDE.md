# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Undefined 是一个基于 Python 异步架构的高性能 QQ 机器人平台，采用自研 Skills 架构，通过 OneBot V11 协议（NapCat/Lagrange.Core）与 QQ 通信，支持多个智能 Agent 协作处理复杂任务。

- Python 版本：3.11~3.13
- 包管理：uv + hatchling
- 主包路径：`src/Undefined/`
- 入口点：`Undefined.main:run`（机器人）、`Undefined.webui:run`（WebUI）

## 常用命令

```bash
# 安装依赖
uv sync

# 启动机器人（二选一，不可同时运行）
uv run Undefined
uv run Undefined-webui

# 代码检查（ruff 使用默认规则，无额外 ruff.toml）
uv run ruff format .
uv run ruff check .
uv run mypy .              # strict 模式，ignore_missing_imports=true

# 运行测试（pytest-asyncio，asyncio_mode="auto"）
uv run pytest tests/
uv run pytest tests/test_xxx.py           # 单个测试文件
uv run pytest tests/test_xxx.py::test_fn  # 单个测试函数

# Playwright 浏览器安装（网页浏览功能需要）
uv run playwright install
```

## 核心架构（8 层）

消息流：用户 → OneBot协议端 → `OneBotClient`(onebot.py) → `MessageHandler`(handlers.py) → 安全检测/命令分发/AI协调 → `QueueManager` → `AIClient` → LLM API → 工具执行 → 回复

关键模块：

| 层 | 核心文件 | 职责 |
|---|---------|------|
| 入口 | `main.py`, `config/manager.py`, `onebot.py`, `context.py` | 启动、配置管理、WS客户端、请求上下文（contextvars） |
| 消息处理 | `handlers.py`, `services/security.py`, `services/command.py`, `services/ai_coordinator.py`, `services/queue_manager.py` | 安全检测、命令分发、AI协调、队列调度 |
| AI核心 | `ai/client.py`, `ai/prompts.py`, `ai/llm.py`, `ai/tooling.py`, `ai/multimodal.py`, `ai/summaries.py` | AI客户端、提示词构建、模型请求、工具管理、多模态分析、总结 |
| Skills | `skills/tools/`, `skills/toolsets/`, `skills/agents/`, `skills/anthropic_skills/` | 基础工具、工具集、智能体、Anthropic Skills |
| 存储 | `memory.py`, `utils/history.py`, `end_summary_storage.py`, `faq.py`, `scheduled_task_storage.py`, `token_usage_storage.py` | 记忆、历史、总结、FAQ、定时任务、Token统计 |
| IO | `utils/io.py` | 异步安全IO（文件锁+原子写入） |

## Skills 技能系统

Skills 是核心扩展机制，分四类，全部通过 `config.json`（OpenAI function calling 格式）+ `handler.py` 自动发现注册：

### 基础工具 (`skills/tools/{tool_name}/`)
- 原子操作，直接暴露给主 AI
- 必须实现 `async def execute(args: dict, context: dict) -> str`

### 工具集 (`skills/toolsets/{category}/{tool_name}/`)
- 按类别分组，注册名为 `{category}.{tool_name}`（如 `render.render_html`）
- 8 大类：group, messages, memory, notices, render, scheduler, mcp, cognitive

### 智能体 (`skills/agents/{agent_name}/`)
- 每个 Agent 目录包含：`config.json`, `handler.py`, `prompt.md`, `intro.md`, `tools/`（子工具）
- 可选：`mcp.json`（Agent 私有 MCP）、`anthropic_skills/`（Agent 私有 Skills）
- Agent 的 config.json 统一使用 `prompt` 参数接收用户需求
- Agent handler 应使用 `skills/agents/runner.py` 的 `run_agent_with_tools()` 统一执行入口，它处理 prompt 加载、LLM 迭代、tool call 并发执行、结果回填
- Agent 通过 `context["ai_client"].request_model()` 调用模型，确保 Token 统计一致
- 6 个内置 Agent：info_agent, web_agent, file_analysis_agent, naga_code_analysis_agent, entertainment_agent, code_delivery_agent

### Anthropic Skills (`skills/anthropic_skills/{skill_name}/SKILL.md`)
- 遵循 agentskills.io 标准，YAML frontmatter（name + description）+ Markdown 正文
- 注册为 `skills-_-<name>` function tool，渐进式披露

### handler.py 中可用的 `context` 字典关键 key
- `ai_client`：AIClient 实例，用于 `request_model()` 调用模型
- `onebot_client`：OneBotClient 实例，用于发送消息/调用 OneBot API
- `config`：全局 Config 对象
- `end_summaries`：deque，短期总结列表
- `end_summary_storage`：EndSummaryStorage 实例
- `conversation_ended`：设为 `True` 通知调用方对话结束
- `agent_history`：Agent 调用时的上下文历史消息列表

## 关键设计模式

### 请求上下文
基于 `contextvars` 的 `RequestContext`（`context.py`），每个请求自动 UUID 追踪，通过 `get_group_id()`, `get_user_id()`, `get_request_id()` 获取。

### 队列模型（车站-列车）
`QueueManager` 按模型隔离队列，四级优先级（超管 > 私聊 > @群聊 > 普通群聊），可配置发车间隔，非阻塞调度。

### 异步 IO
所有磁盘操作通过 `utils/io.py`，使用 `asyncio.to_thread` + 跨平台文件锁（flock/msvcrt）+ 原子写入（`os.replace`）。**不要**在 handler.py 中直接使用阻塞式 `open()` 读写。

### 资源加载
`utils/resources.py` 实现可覆盖资源加载：运行目录 `./res/...` > 安装包自带资源 > 仓库结构兜底。

### 配置系统
- 主配置：`config.toml`（TOML 格式，支持热更新）
- 配置模型：`config/models.py`，四类模型配置（chat/vision/agent/security）
- 运行时动态数据：`config.local.json`（自动生成，勿提交）
- 需重启的配置项：`log_level`, `logging.file_path/max_size_mb/backup_count/tty_enabled`, `onebot.ws_url/token`, `webui.*`

## 开发注意事项

- Skills 的 handler.py 中**避免引用** `skills/` 外部的本地模块，外部依赖通过 `context` 注入
- 提示词文件在 `res/prompts/`，主系统提示词为 `undefined.xml`（NagaAgent 模式用 `undefined_nagaagent.xml`）
- 工具名中的 `.` 在发送给模型前会映射为 `config.tools.dot_delimiter`（默认 `-_-`）
- XML 注入防护：结构化 Prompt 使用 `utils/xml.py` 做转义
- NagaAgent 子模块在 `code/NagaAgent/`，通过 `git submodule update --init --recursive` 初始化
- 热重载默认开启（`skills.hot_reload = true`），扫描 `skills/` 目录变更自动重载
- Agent intro 自动生成：按代码 hash 检测变更，生成 `intro.generated.md`，不要手动编辑
- 数据持久化在 `data/` 目录：`history/`, `faq/`, `token_usage_archives/`, `memory.json`, `end_summaries.json`, `scheduled_tasks.json`

## 不应提交的文件

- `config.toml`（含 API key 等敏感信息）
- `config.local.json`（运行时自动生成的动态数据）
- `data/`（运行时数据目录）
- `intro.generated.md`（Agent 自动生成的介绍文件）
