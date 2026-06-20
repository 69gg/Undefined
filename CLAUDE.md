# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Undefined 是基于 Python asyncio 的高性能 QQ 机器人平台，通过 OneBot V11 协议（NapCat/Lagrange.Core）与 QQ 通信，搭载认知记忆架构、自研 Skills 系统、本地知识库、全局表情包库，以及 Management-first WebUI / Desktop / Android 管理端。

## 开发命令

```bash
# 依赖安装 / 初始化
uv sync
uv run playwright install       # 页面截图等能力依赖的浏览器运行时

# 启动
uv run Undefined-webui          # 启动 Management-first WebUI（推荐入口）
uv run Undefined                # 直接启动 Bot

# WebUI 自动启动 Bot
# 配置 [webui].autostart_bot = true 后，运行 uv run Undefined-webui 会自动拉起 bot 进程
# 默认为 false，保持传统手动启动行为
# 注意：该配置仅在 WebUI 启动时生效，运行时修改需重启 WebUI

# 代码质量（提交前必须全部通过）
uv run ruff format .
uv run ruff check .
uv run mypy .                   # strict=true
uv run pytest tests/
uv run pytest tests/test_xxx.py
uv run pytest tests/test_xxx.py::test_func -v
uv build --wheel                # 校验打包与资源包含

# 前端 / 桌面端（仅改动 apps/undefined-console/ 或 apps/undefined-chat/ 或 webui/static/js/ 时需要）
cd apps/undefined-console && npm ci && npm run check
cd apps/undefined-console && npm run dev
cd apps/undefined-console && npm run tauri:dev

cd apps/undefined-chat && npm ci && npm run check
cd apps/undefined-chat && npm run tauri:dev

# Git hooks 安装
bash scripts/install_git_hooks.sh
# pre-commit 自动执行：ruff format --check + ruff check + mypy
# 含 JS/Tauri 改动时额外执行：Biome + TypeScript + cargo fmt/check
```

## 代码规范

- **类型注释**：所有 Python 代码必须有完整类型注释，mypy strict 模式
- **异步 IO**：磁盘读写必须走 `utils/io.py`（`asyncio.to_thread` + 跨平台文件锁 + 原子写入），禁止在事件循环中直接阻塞 IO
- **Python 版本**：`>=3.11, <3.14`（推荐 3.12）
- **测试**：pytest + pytest-asyncio，`asyncio_mode = "auto"`
- **前端格式化**：`src/Undefined/webui/static/js/` 由根目录 `biome.json` 管理；`apps/undefined-console/` 和 `apps/undefined-chat/` 走 Biome + TypeScript + Cargo 检查
- **版本号同步**：发布版本时优先使用 `uv run python scripts/bump_version.py <version>`，统一同步 Python 包、console、chat 与 Tauri 版本号
- **Git hooks**：优先通过 `scripts/install_git_hooks.sh` 安装，不要手动维护 `core.hooksPath`

## 架构分层

核心源码位于 `src/Undefined/`，主要模块如下：

| 目录 / 文件 | 职责 |
|---|---|
| `ai/` | AI 运行时核心：`client.py`(主入口)、`llm.py`(模型请求)、`prompts.py`(Prompt 构建)、`tooling.py`(工具管理)、`multimodal.py`(多模态)、`model_selector.py`(模型选择)、`summaries.py`(短期总结) |
| `services/` | 运行服务：`ai_coordinator.py`(协调器+队列投递)、`queue_manager.py`(车站-列车队列)、`message_batcher.py`(同 sender 短时合并)、`command.py`(命令分发)、`model_pool.py`(多模型池)、`security.py`(安全防护) |
| `skills/` | 热重载技能系统：`tools/`(原子工具)、`toolsets/`(按域分组工具)、`agents/`(智能体)、`commands/`(斜杠指令)、`anthropic_skills/`(SKILL.md 知识注入) |
| `cognitive/` | 认知记忆：`service.py`(入口)、`vector_store.py`(ChromaDB)、`historian.py`(后台史官异步改写+侧写合并)、`job_queue.py`、`profile_storage.py` |
| `memes/` | 表情包库：两阶段 AI 管线、异步处理队列、SQLite 元数据、ChromaDB 向量检索 |
| `knowledge/` | 本地知识库：文本切分、嵌入、重排、ChromaDB 存储与运行时检索 |
| `arxiv/` | arXiv 论文解析、元信息获取、PDF 下载与发送 |
| `bilibili/` | B 站链接/BV 解析、视频下载与发送 |
| `github/` | GitHub public 仓库解析、API 获取与图片卡片发送 |
| `api/` | Runtime API / Management API 相关服务；路由拆分在 `api/routes/`，包含 `chat`、`cognitive`、`health`、`memes`、`memory`、`naga`、`system`、`tools` |
| `webui/` | aiohttp 管理控制台；路由拆分在 `webui/routes/`，覆盖配置、日志、运行态、表情包与系统管理 |
| `mcp/` | MCP 工具注册、连接与转换 |
| `config/` | 配置系统：`loader.py`(TOML 解析+类型化)、`models.py`(数据模型)、`hot_reload.py`(热更新) |
| `attachments.py` | 富媒体/附件注册、作用域隔离、`<attachment uid="..."/>` 统一标签（`<pic>` 向后兼容）渲染 |
| `utils/` | `io.py`(异步 IO)、`history.py`(消息历史)、`paths.py`、`logging.py`、`sender.py` 等通用能力 |

### 消息处理流程

```text
OneBot WebSocket → onebot.py → handlers.py
  → 附件登记 / 访问控制 / 表情包入库
  → SecurityService(注入检测)
  → CommandDispatcher(斜杠指令，命中即结束后续处理)
  → skills/pipelines(Bilibili / arXiv / GitHub 并行自动提取)
  → MessageBatcher(同 sender 短时合并；拍一拍/buffer 内 @bot 旁路)
  → AICoordinator → QueueManager(按模型隔离, 4 级优先级)
  → AIClient → LLM API / Skills / MCP

Management / Runtime 请求 → webui/app.py 或 api/app.py → routes/*
  → 配置、日志、记忆、工具调用、AI Chat 等能力
```

### 多模型池分工

- `ai/model_selector.py` — 纯选择逻辑（策略 / 偏好 / compare 状态），无 IO 副作用
- `services/model_pool.py` — 私聊交互服务，持有 ai/config/sender，处理 `/compare`、`选X`、`select_chat_config`
- `services/ai_coordinator.py` — 持有 `ModelPoolService`（`self.model_pool`），私聊队列投递时通过它选模型
- `handlers.py` — 私聊消息只调 `await self.ai_coordinator.model_pool.handle_private_message(user_id, text)`，不直接感知选择细节
- `skills/agents/runner.py` — Agent 直接调用 `ai_client.model_selector.select_agent_config(...)`，无 `hasattr`
- 默认关闭：`models.pool_enabled = false`；群聊不参与多模型，始终走主模型

### Skills 系统

- **热重载**：自动扫描 `skills/` 下 `config.json` / `handler.py` 变更并重载
- **自动处理管线**：`skills/pipelines/<name>/` 使用 `config.json + handler.py`，在斜杠命令之后、AI 自动回复之前并行检测/处理；命令输入和命令输出要写入历史，管线输出通过 `MessageSender` 自动写历史并登记本地媒体/文件附件 UID。
- **Skills handler 不引用 `skills/` 外的本地模块**，依赖通过 context 注入
- **Agent 标准结构**：`config.json` + `handler.py` + `prompt.md` + `intro.md` + `mcp.json`(可选) + `anthropic_skills/`(可选)
- **共享授权**：通过 `callable.json` 将工具或 Agent 白名单暴露给其他 Agent
- **Anthropic Skills**：支持 SKILL.md 目录结构与渐进式披露

#### 关键工具说明

- `group.get_member_info`：支持 `brief` 参数（默认 false）。当 `brief=true` 时只返回当前昵称（群名片优先，否则 QQ 昵称），便于快速称呼用户。
- `group.get_avatar`：接受 `user_id` 与可选 `size`（40/100/140/640），下载 QQ 头像并注册为附件，返回 `<attachment uid="..."/>` 标签。
- 统一附件标签：推荐使用 `<attachment uid="..."/>`，系统根据 UID 前缀（`pic_`/`file_`）自动区分图片与文件。旧 `<pic uid="..."/>` 语法向后兼容。
- 远程附件默认按 `[attachments].remote_download_max_size_mb` 限制下载缓存；超过上限或配置为 `0` 时只登记 URL 引用（`source_ref`），避免大文件造成磁盘和延迟压力。

### 队列模型

车站-列车模型（QueueManager）：按模型隔离队列组，4 级优先级（超管 > 私聊 > @提及 > 普通群聊），普通队列自动修剪保留最新 2 条，非阻塞按节奏发车（默认 1Hz）。

### 同 sender 短时消息合并（MessageBatcher）

同一 sender 在 `[message_batcher].window_seconds` 内连续发送的多条消息会合并到同一轮 AI 调用，AI 一次性看到全部 `<message>` 块自行识别“独立请求/修正/打断”。拍一拍永远旁路立即处理；群聊已有 buffer 时新到的 @bot 也单独立即处理；首条 @bot 进入 buffer 时整批走 mention 队列。可选开启投机预发送 `pre_send_seconds < window_seconds`：静默到该阈值先把 batch 提前发给 LLM 抢时间，新消息在 inflight 未发出任何消息时可取消该调用。`enabled=false` 行为退化回旧版。详见 [docs/message-batching.md](docs/message-batching.md)。

### 存储与数据

- `data/history/` — 消息历史（`group_*.json` / `private_*.json`，默认 10000 条，可通过 `[history]` 调整，0 = 无限）
- `data/cognitive/` — ChromaDB 向量库 + `profiles/` 侧写 + `queues/` 任务队列
- `data/memes/` — 表情包库（`blobs/` 原图、`previews/` 预览图、`memes.sqlite3` 元数据、`chromadb/` 向量检索）
- `data/cache/` — 附件、下载、渲染与 WebUI 文件缓存
- `data/attachment_registry.json` — 附件注册表
- `data/memory.json` — 置顶备忘录（500 条上限）
- `data/end_summaries.json` — 短期总结存储
- `data/scheduled_tasks.json` — 定时任务存储
- `data/faq/` — FAQ 存储
- `data/token_usage.jsonl` — Token 统计（自动 gzip 归档）
- `knowledge/` — 本地知识库数据目录（`texts/`、`intro.md`、`chroma/` 等）
- `res/prompts/` — 系统提示词模板

## 提示词约定

系统提示词（`res/prompts/undefined.xml`）包含用户识别规则：
- 以 QQ 号（`sender_id`）为用户唯一标识，昵称可能随时变动
- 称呼用户时使用当前最新昵称，不确定时可调用 `group.get_member_info(brief=true)` 查询
- 认知记忆（observations）必须包含 QQ 号，格式如：“QQ号12345678（昵称张三）做了某事”

## 配置系统

- 主配置：`config.toml`（从 `config.toml.example` 复制）
- 配置热更新：`config.reload()` 触发回调
- MCP 配置：`config/mcp.json`（全局）或 `agents/<name>/mcp.json`（Agent 私有）
- 脚本 `scripts/sync_config_template.py` 可将新配置项同步到已有 `config.toml`

## 运维脚本

- `scripts/install_git_hooks.sh` — 安装 Git hooks（设置 `.githooks`）
- `scripts/sync_config_template.py` — 同步配置模板新增项（支持 `--dry-run`）
- `scripts/reembed_cognitive.py` — 更换嵌入模型后重建认知向量库（支持 `--events-only` / `--profiles-only` / `--batch-size` / `--dry-run`）
- `scripts/bump_version.py` — 同步更新 Python / console / Tauri 版本号，并可选择连同 lock 文件一起更新

## 跨平台控制台

`apps/undefined-console/` 是基于 Tauri v2 + TypeScript + Vite 的管理客户端，支持 Windows / macOS / Linux / Android，连接同一套 Management API 与 Runtime API。

`apps/undefined-chat/` 是原生优先的 WebChat 客户端，基于 Tauri v2 + React，直接连接 Runtime API，面向长期挂起、桌面/移动端聊天使用场景。采用莫兰迪橙色系（Morandi Orange）设计，与 WebUI 保持视觉一致性。它移植 WebUI webchat 的核心聊天功能，并在事件流（SSE 优先 + JSON fallback 双通道）、桌面快捷键、图片查看（缩放/旋转/全屏）、安全存储（系统 keyring / Android Keystore）等方面做了原生增强；HTML 采用 sanitize 内联渲染 + 独立预览窗口隔离运行的双层策略。详见 [docs/undefined-chat.md](docs/undefined-chat.md)。
