# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Undefined 是基于 Python asyncio 的高性能 QQ 机器人平台，通过 OneBot V11 协议（NapCat/Lagrange.Core）与 QQ 通信，搭载认知记忆架构和自研 Skills 系统。

## 开发命令

```bash
# 启动
uv run Undefined-webui          # 启动 WebUI 管理控制台（推荐入口）
uv run Undefined                # 直接启动 Bot

# 代码质量（提交前必须全部通过）
uv run ruff format .            # 格式化
uv run ruff check .             # Lint
uv run mypy .                   # 严格类型检查（strict=true）
uv run pytest tests/            # 运行全部测试
uv run pytest tests/test_xxx.py # 运行单个测试文件
uv run pytest tests/test_xxx.py::test_func -v  # 运行单个测试函数

# 前端（仅改动 apps/undefined-console/ 或 webui/static/js/ 时需要）
cd apps/undefined-console && npm install && npm run check

# Git hooks 安装
bash scripts/install_git_hooks.sh
# pre-commit 自动执行：ruff format --check + ruff check + mypy
# 含 JS/Tauri 改动时额外执行：Biome + TypeScript + cargo fmt/check
```

## 代码规范

- **类型注释**：所有 Python 代码必须有完整类型注释，mypy strict 模式
- **异步 IO**：磁盘读写必须走 `utils/io.py`（asyncio.to_thread + 跨平台文件锁 + 原子写入），禁止在事件循环中直接阻塞 IO
- **Python 版本**：>=3.11, <3.14（推荐 3.12）
- **测试**：pytest + pytest-asyncio，asyncio_mode = "auto"
- **JS 格式化**：`biome.json` 管理 `webui/static/js/` 目录

## 架构分层

源码在 `src/Undefined/`，8 层架构：

### 消息处理流程
```
OneBot WebSocket → onebot.py → handlers.py → SecurityService(注入检测)
  → CommandDispatcher(斜杠指令) 或 AICoordinator(AI回复)
  → QueueManager(车站-列车模型,4级优先级) → AIClient → LLM API
```

### 关键模块

| 目录 | 职责 |
|------|------|
| `ai/` | AI 核心：client.py(主入口)、llm.py(模型请求)、prompts.py(Prompt构建)、tooling.py(工具管理)、multimodal.py(多模态)、model_selector.py(模型选择) |
| `services/` | 运行服务：ai_coordinator.py(协调器+队列投递)、queue_manager.py(车站-列车队列)、command.py(命令分发)、model_pool.py(多模型池)、security.py(安全防护) |
| `skills/` | 热重载技能系统：tools/(原子工具)、toolsets/(9类工具集)、agents/(6个智能体)、commands/(斜杠指令)、anthropic_skills/(SKILL.md知识注入) |
| `cognitive/` | 认知记忆：service.py(入口)、vector_store.py(ChromaDB)、historian.py(后台史官异步改写+侧写合并)、job_queue.py、profile_storage.py |
| `config/` | 配置系统：loader.py(TOML解析+类型化)、models.py(数据模型)、hot_reload.py(热更新) |
| `webui/` | aiohttp Web 管理控制台 |
| `api/` | Management API + Runtime API |
| `utils/` | io.py(异步IO)、history.py(消息历史)、paths.py、logging.py、sender.py 等 |

### 多模型池分工
- `ai/model_selector.py` — 纯选择逻辑（策略/偏好/compare状态），无 IO 副作用
- `services/model_pool.py` — 私聊交互服务，持有 ai/config/sender
- `services/ai_coordinator.py` — 持有 `ModelPoolService`（`self.model_pool`），私聊队列投递时通过它选模型
- `handlers.py` — 私聊消息调用 `ai_coordinator.model_pool.handle_private_message()`
- 默认关闭：`models.pool_enabled = false`；群聊不参与多模型，始终走主模型

### Skills 系统
- **热重载**：自动扫描 `skills/` 下 `config.json`/`handler.py` 变更并重载
- **Skills handler 不引用 `skills/` 外的本地模块**，依赖通过 context 注入
- **Agent 标准结构**：`config.json`(工具定义) + `handler.py`(执行逻辑) + `prompt.md`(系统提示) + `intro.md` + `mcp.json`(可选私有MCP)
- **Agent 直接调用** `ai_client.model_selector.select_agent_config(...)`，无 hasattr

### 队列模型
车站-列车模型（QueueManager）：按模型隔离队列组，4 级优先级（超管 > 私聊 > @提及 > 普通群聊），普通队列自动修剪保留最新 2 条，非阻塞按节奏发车（默认 1Hz）。

### 存储与数据
- `data/history/` — 消息历史（group_*.json / private_*.json，10000 条限制）
- `data/cognitive/` — ChromaDB 向量库 + profiles/ 侧写 + queues/ 任务队列
- `data/memory.json` — 置顶备忘录（500 条上限）
- `data/faq/` — FAQ 存储
- `data/token_usage.jsonl` — Token 统计（自动 gzip 归档）
- `res/prompts/` — 系统提示词模板

## 配置系统

- 主配置：`config.toml`（从 `config.toml.example` 复制）
- 配置热更新：`config.reload()` 触发回调
- MCP 配置：`config/mcp.json`（全局）或 `agents/<name>/mcp.json`（Agent 私有）
- 脚本 `scripts/sync_config_template.py` 可同步新配置项到已有 config.toml

## 运维脚本

- `scripts/sync_config_template.py` — 同步配置模板新增项（支持 `--dry-run`）
- `scripts/reembed_cognitive.py` — 更换嵌入模型后重建向量库（支持 `--events-only`/`--profiles-only`/`--batch-size`/`--dry-run`）
- `scripts/install_git_hooks.sh` — 安装 Git hooks

## 跨平台控制台

`apps/undefined-console/` — Tauri + Vue3 + TypeScript，支持 Windows/macOS/Linux/Android，连接同一 Management API。
