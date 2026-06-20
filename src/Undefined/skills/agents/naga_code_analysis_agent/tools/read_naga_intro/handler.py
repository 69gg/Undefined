from typing import Any, Dict

# NagaAgent 项目介绍内容（直接嵌入以保证稳定性）
NAGA_INTRO_CONTENT = """
## 项目概览
- README 标识版本 5.1.0。
- 后端：Python 3.11 + FastAPI + OpenAI/Anthropic/LiteLLM 兼容调用 + Pydantic。
- 前端：Vue 3 + TypeScript + Vite + Electron，入口在 `frontend/`。
- 统一入口：`main.py`，负责启动后台任务、API Server、MCP Server、Agent Server、TTS 等服务。
- 配置中心：`system/config.py` + `config.json`/`config.json.example`，支持运行时配置同步与热更新。
- 默认端口：API 8000、Agent 8001、MCP 8003、TTS 5048、ASR 5060。
- 核心能力：流式工具调用、GRAG 知识图谱记忆、MCP 服务、Anthropic-style skills、OpenClaw 电脑操作、DogTag 心跳/屏幕主动感知、旅行探索、游戏攻略。

## 快速定位
- 服务并行启动逻辑：`main.py`
- API 应用入口与共享状态：`apiserver/api_server.py`
- API 路由（如 `/chat`、`/chat/stream`、配置、会话、工具、论坛、扩展）：`apiserver/routes/`
- 模型调用/参数拼装：`apiserver/llm_service.py`
- Agentic 工具调用循环：`apiserver/agentic_tool_loop.py`
- 流式文本处理与 TTS 推送：`apiserver/streaming_tool_extractor.py`
- 会话与消息管理：`apiserver/message_manager.py`
- 上下文压缩：`apiserver/context_compressor.py`
- NagaCAS 登录与认证：`apiserver/naga_auth.py`、`apiserver/routes/auth.py`
- 运行时控制（如语音暂停）：`apiserver/naga_control.py`
- Agent 调度服务：`agentserver/agent_server.py`
- DogTag 心跳/屏幕主动感知：`agentserver/dogtag/`
- OpenClaw 连接与运行时：`agentserver/openclaw/`
- MCP 管理与服务注册：`mcpserver/mcp_manager.py`、`mcpserver/mcp_registry.py`
- 内置 MCP agents：`mcpserver/agent_*`
- 全局配置结构与端口：`system/config.py`
- 配置热更新接口：`system/config_manager.py`
- 角色包与提示词：`system/character_bundle.py`、`system/prompts/`
- 语音输出服务：`voice/output/start_voice_service.py`、`voice/output/server.py`
- 实时语音输入链路：`voice/input/voice_realtime/`
- 前端页面路由与主界面：`frontend/src/views/`、`frontend/src/App.vue`
- 前端 API 封装：`frontend/src/api/`
- Electron 主进程与后端拉起：`frontend/electron/main.ts`、`frontend/electron/modules/backend.ts`
- 技能定义：`skills/*/SKILL.md`
- 游戏攻略/画面理解：`guide_engine/`
- 长期记忆（GRAG/图谱）：`summer_memory/`

## 目录与文件说明

| 路径 | 作用 | 常改文件 |
|---|---|---|
| `main.py` | 项目总入口，负责并行启动服务、端口检查、代理初始化 | `main.py` |
| `apiserver/` | 对话 API 核心（路由、LLM 调用、流式输出、工具调用循环、认证、论坛代理） | `api_server.py`、`routes/*.py`、`llm_service.py`、`agentic_tool_loop.py` |
| `agentserver/` | Agent 调度、DogTag 心跳/屏幕感知、OpenClaw 集成 | `agent_server.py`、`dogtag/*.py`、`openclaw/*.py` |
| `mcpserver/` | MCP 服务管理、内置 MCP agents、统一工具调用路由 | `mcp_manager.py`、`mcp_registry.py`、`agent_*` |
| `system/` | 配置系统、提示词、环境检测、日志初始化 | `config.py`、`config_manager.py`、`system_checker.py`、`prompts/*.txt` |
| `voice/` | 语音输入输出能力（TTS/Realtime） | `output/start_voice_service.py`、`output/server.py`、`input/unified_voice_manager.py` |
| `summer_memory/` | 记忆系统与图谱检索（五元组、RAG、任务记忆） | `memory_manager.py`、`quintuple_extractor.py`、`quintuple_rag_query.py` |
| `frontend/` | Vue3 + Electron 前端 | `src/views/*.vue`、`src/api/*.ts`、`electron/main.ts` |
| `guide_engine/` | 游戏攻略、截图识别、RAG/图谱查询与提示词管理 | `guide_service.py`、`query_router.py`、`screenshot_provider.py` |
| `skills/` | 内置技能定义（SKILL.md） | `*/SKILL.md` |
| `scripts/` | 构建/自动化脚本 | `build-win.py` |
| `logs/` | 日志与运行期输出目录 | `logs/*.log` |

## 根目录关键文件（排查优先看）
- `config.json`：运行配置（若不存在会尝试由 `config.json.example` 生成）。
- `pyproject.toml`：项目版本、Python 依赖与版本约束（`>=3.11,<3.12`）。
- `uv.lock`：`uv` 锁定依赖版本。
- `requirements.txt`：传统 pip 安装依赖清单。
- `build.md`：完整打包说明。
- `build.py` / `naga-backend.spec`：跨平台构建与 PyInstaller 打包配置。
- `start.bat`、`setup_venv.bat`：Windows 启动/环境脚本。
- `proactive_vision_config.json`：屏幕主动感知默认/运行配置。

## 当前目录状态提示
- 现阶段开发优先从 `main.py`、`apiserver/`、`agentserver/`、`mcpserver/`、`system/`、`voice/`、`frontend/`、`guide_engine/`、`summer_memory/`、`skills/` 入手。
- `characters/` 存放角色资源，`vendor/openclaw/` 是 OpenClaw vendor 源码/运行时相关内容。

## 环境准备
```bash
# 推荐使用 uv
uv sync

# 可选：传统 venv
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
- Python 版本必须满足：`>=3.11,<3.12`。
- `api.api_format` 支持 `openai` 与 `anthropic`，默认示例为 DeepSeek OpenAI-compatible API。
- 默认优先使用 `uv run ...` 运行命令。

## 启动相关
- 服务统一入口在 `main.py`。
- 前端 Electron 主进程会通过 `frontend/electron/modules/backend.ts` 拉起后端。
- API 与 Agent Server 可从 `apiserver/`、`agentserver/` 下的入口文件继续追踪。

## 打包相关
- 跨平台构建入口文件：`build.py`。
- Windows 构建脚本位于 `scripts/`。
- 详细流程见：`build.md`、`docs/build-windows.md`。
"""


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    return f"{NAGA_INTRO_CONTENT}"
