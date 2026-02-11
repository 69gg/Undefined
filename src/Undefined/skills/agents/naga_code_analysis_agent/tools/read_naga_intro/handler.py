from typing import Any, Dict

# NagaAgent 项目介绍内容（直接嵌入以保证稳定性）
NAGA_INTRO_CONTENT = """
## 项目概览
- 后端：Python 3.11 + FastAPI + LiteLLM + Pydantic。
- 前端：Vue 3 + TypeScript + Vite + Electron + PrimeVue + UnoCSS。
- 统一入口：`main.py`（并行拉起 API/Agent/TTS 等服务）。
- 配置中心：`system/config.py` + `config.json`（支持 JSON5 注释解析）。
- 默认端口：API 8000、Agent 8001、MCP 8003（保留）、TTS 5048。

## 快速定位
- 服务并行启动逻辑：`main.py`
- API 路由（如 `/chat`、`/chat/stream`）：`apiserver/api_server.py`
- 模型调用/参数拼装：`apiserver/llm_service.py`
- 流式工具调用提取：`apiserver/streaming_tool_extractor.py`
- 会话与消息管理：`apiserver/message_manager.py`
- Agent 调度/OpenClaw 执行：`agentserver/agent_server.py`
- 任务调度与任务记忆：`agentserver/task_scheduler.py`
- OpenClaw 连接与运行时：`agentserver/openclaw/`
- 全局配置结构与端口：`system/config.py`
- 配置热更新接口：`system/config_manager.py`
- 系统提示词：`system/prompts/conversation_style_prompt.txt`、`system/prompts/conversation_analyzer_prompt.txt`
- 语音输出服务：`voice/output/start_voice_service.py`、`voice/output/server.py`
- 实时语音输入链路：`voice/input/voice_realtime/`
- 前端页面路由与主界面：`frontend/src/views/`、`frontend/src/App.vue`
- 前端 API 封装：`frontend/src/api/`
- Electron 主进程与后端拉起：`frontend/electron/main.ts`、`frontend/electron/modules/backend.ts`
- 长期记忆（GRAG/图谱）：`summer_memory/`

## 目录与文件说明

| 路径 | 作用 | 常改文件 |
|---|---|---|
| `main.py` | 项目总入口，负责并行启动服务、端口检查、代理初始化 | `main.py` |
| `apiserver/` | 对话 API 核心（路由、LLM 调用、流式输出、工具调用循环） | `api_server.py`、`llm_service.py`、`streaming_tool_extractor.py`、`message_manager.py` |
| `agentserver/` | 任务调度与电脑控制执行服务（OpenClaw） | `agent_server.py`、`task_scheduler.py`、`openclaw/*.py` |
| `system/` | 配置系统、提示词、环境检测、日志初始化 | `config.py`、`config_manager.py`、`system_checker.py`、`prompts/*.txt` |
| `voice/` | 语音输入输出能力（TTS/Realtime） | `output/start_voice_service.py`、`output/server.py`、`input/unified_voice_manager.py` |
| `summer_memory/` | 记忆系统与图谱检索（五元组、RAG、任务记忆） | `memory_manager.py`、`quintuple_extractor.py`、`quintuple_rag_query.py` |
| `frontend/` | Vue3 + Electron 前端 | `src/views/*.vue`、`src/api/*.ts`、`electron/main.ts` |
| `skills/` | 内置技能定义（SKILL.md） | `*/SKILL.md` |
| `scripts/` | 构建/自动化脚本 | `build-win.py` |
| `logs/` | 日志与运行期输出目录 | `logs/*.log` |

## 根目录关键文件（排查优先看）
- `config.json`：运行配置（若不存在会尝试由 `config.json.example` 生成）。
- `pyproject.toml`：Python 依赖与版本约束（`>=3.11,<3.12`）。
- `uv.lock`：`uv` 锁定依赖版本。
- `requirements.txt`：传统 pip 安装依赖清单。
- `build.md`：完整打包说明。
- `naga-backend.spec`：PyInstaller 打包配置。
- `start.bat`、`setup_venv.bat`：Windows 启动/环境脚本。

## 当前目录状态提示
- `game/`、`mcpserver/`、`mqtt_tool/`、`nagaagent_core/`、`models/`、`ui/` 目前主要是历史目录/缓存占位（源码文件基本不在这些目录中）。
- 现阶段开发优先从 `main.py`、`apiserver/`、`agentserver/`、`system/`、`voice/`、`frontend/`、`summer_memory/` 入手。

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
- 默认优先使用 `uv run ...` 运行命令。

## 启动命令
```bash
cd frontend/
npm run dev
# 前端 Electron 主进程会调用 backend 模块拉起根目录 main.py
```

## 打包相关
- Windows 一键构建：`python scripts/build-win.py`。
- 详细流程见：`build.md`。
"""


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    return f"{NAGA_INTRO_CONTENT}"
