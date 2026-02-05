from typing import Any, Dict

# NagaAgent 项目介绍内容（直接嵌入以保证稳定性）
NAGA_INTRO_CONTENT = """
# NagaAgent 指南

## 快速定位
- 入口：`main.py`（UI + 后台并行启动 API/Agent/MCP/TTS 等）
- Python：3.11，包管理用 `uv`（`pyproject.toml` + `uv.lock`）
- 前端：`frontend/`（Vue 3 + TS + Vite + UnoCSS；npm + `package-lock.json`）
- 服务目录：`apiserver/`、`agentserver/`、`mcpserver/`、`voice/`、`system/`

## Cursor/Copilot 规则
- Cursor：未发现 `.cursor/rules/` 或 `.cursorrules`
- Copilot：未发现 `.github/copilot-instructions.md`
如新增/更新上述规则文件，请同步更新本 AGENTS.md。

## 初始化/运行/构建/检查
```bash
# 初始化（推荐：会安装 uv、sync 依赖、装 Playwright Chromium、复制 config.json）
python setup.py

# 手动安装依赖（含 dev 工具：ruff/black/pytest）
uv sync --all-groups

# 启动主程序（最常用）
uv run python main.py

# 环境检测
uv run python main.py --quick-check
uv run python main.py --check-env --force-check

# 单服务调试
uv run python apiserver/start_server.py api
uv run python -m uvicorn agentserver.agent_server:app --host 0.0.0.0 --port 8001

# 前端
cd frontend && npm ci
npm run dev
npm run build
npm run preview

# Lint / Format
uv run ruff check .
uv run ruff check . --fix
uv run ruff format .
uv run black . --line-length 120

# 测试（pytest；当前仓库测试目录不固定，建议新增放到 tests/test_*.py）
uv run pytest
uv run pytest path/to/test_file.py
uv run pytest path/to/test_file.py::test_name
uv run pytest -k "keyword" -q

# 脚本式冒烟（非 pytest）
uv run python game/simple_test.py
uv run python game/minimal_test.py
uv run python game/full_flow_test.py

# 打包（危险：会删除 .venv；仅在需要发布整合包时运行）
python build.py
```

## 常见坑（先看再改）
- `requirements.txt` 主要用于传统 pip；开发调试优先用 `uv sync` + `uv run ...` 保证依赖与锁文件一致
- `build.py` 会删除 `.venv` 并下载运行时文件：只在制作发布整合包时使用
- `main.py` 为打包/跨平台做了不少兼容逻辑（PyInstaller、Windows socket 常量等）；改动时避免破坏启动路径
- `apiserver/` 部分依赖通过 `nagaagent_core.api` 重新导出；新增端点时优先沿用同文件的导入方式
- 本地调用 `http://127.0.0.1/...` 时，若机器设置了代理，可能导致请求走代理失败：必要时设置 `NO_PROXY=127.0.0.1,localhost`

端口：可在 `config.json` / `system.config.get_server_port()` 配置；常见端口为 8000/8001/8003/5048。

## 仓库结构与边界
- `main.py`：UI 启动 + 后台线程启动各服务；含部分 PyInstaller/Windows 兼容逻辑
- `apiserver/`：对外 REST API；流式对话/工具回调/文档上传等（大量逻辑在 `apiserver/api_server.py`）
- `agentserver/`：意图分析与电脑控制任务调度；常用独立启动便于调试
- `system/`：配置加载、热更新、环境检测；读写 `config.json` 有编码/注释兼容逻辑
- `voice/`：语音输入/输出/TTS 服务
- `mcpserver/`：MCP 工具服务集合；部分子目录自带 `requirements.txt`/`pyproject.toml`（不一定走顶层依赖）

当你改动跨目录接口（例如 API 调 agentserver、UI 调 apiserver）时，优先保证请求/响应字段兼容，并更新相关 README/示例。

## 关键代码导读（建议先读这些文件）

### 启动与服务编排
- `main.py`：入口脚本，负责 UI 启动与后台服务并行启动
- 关键点：
  - 打包环境会检测 `_internal` 并 `chdir`（不要破坏相对路径假设）
  - 通过 `sys.path.insert` 优先加载本仓库的 `nagaagent-core`（避免导入到系统旧版本）
  - `ServiceManager.start_all_servers()` 用线程启动 API/MCP/Agent/TTS，并先做端口占用预检查
  - 代理处理：当 `config.api.applied_proxy` 为 False，会清空 `HTTP_PROXY/HTTPS_PROXY`，避免本地回环请求走代理

### API Server（对外对话入口）
- `apiserver/api_server.py`：FastAPI 应用与主要端点
  - `/chat`：非流式对话；使用 `MessageManager` 维护 session + 历史上下文
  - `/chat/stream`：SSE 流式对话；边生成边把文本喂给“按句切割器”以驱动 TTS
  - `use_self_game`：在启用配置时走 `game.naga_game_system.NagaGameSystem`（失败可回退普通对话）
  - `tool_result_callback` / `ui_notification`：用于 MCP/工具执行结果回调后，驱动 UI 显示新的 AI 回复

### 会话/上下文与日志
- `apiserver/message_manager.py`：统一会话管理
  - `create_session()`：可按配置从 `logs/YYYY-MM-DD.log` 解析历史对话作为上下文（持久化上下文）
  - `build_conversation_messages()`：组装 system prompt + 历史 + 当前消息；会自动追加“当前时间信息”
  - `save_conversation_and_logs()`：保存历史 + 写日志；若启用 GRAG 记忆，异步触发五元组提取任务

### 流式文本切割与 TTS
- `apiserver/streaming_tool_extractor.py`：名字历史原因，当前职责是“流式按句切割并发给语音模块”，不负责工具调用解析
  - `process_text_chunk()`：逐字符累积，遇到句末标点就把完整句子异步送到 `voice_integration.receive_text_chunk`

### 配置系统与热更新
- `system/config.py`：Pydantic 配置模型 + `json5` 加载（支持注释）+ `charset_normalizer` 自动识别编码
  - `get_server_port()`：集中端口管理（api/agent/mcp/tts/asr）
  - 注意：`NagaConfig.window` 是 `QWidget`，仅用于运行态，不应序列化回 `config.json`
- `system/config_manager.py`：配置热更新/监视器；写回配置时尽量保留原文件编码

### Agent/MCP/Voice 服务（独立子服务）
- `agentserver/agent_server.py`：电脑控制/任务调度服务；`/schedule` 接收 agent_calls 并异步执行，可选回调
- `mcpserver/mcp_server.py`：MCP 调度入口；包含幂等缓存、去重、并发限制；初始化时自动注册 MCP 服务
- `voice/output/start_voice_service.py`：语音输出 HTTP 服务启动器（WSGI）；依赖缺失时会提示安装

### 前端（如需改 UI）
- `frontend/src/App.vue`：页面骨架与 Live2D 叠加层
- `frontend/src/components/Live2dModel.vue`：PIXI + `pixi-live2d-display` 初始化；失败必须可降级（当前已 try/catch）

## 代码风格与约定
### 通用
- 变更“最小且一致”：先读相邻代码再定风格/依赖
- 编码默认 UTF-8；避免在 `print()`/日志中输出 emoji（Windows 控制台/GBK 常见崩溃点）
- 严禁提交密钥/令牌：`config.json` 可能含 `api_key`；新增配置项要同步 `config.json.example`
- 涉及本地回环请求（127.0.0.1/localhost）时，注意代理环境变量；必要时设置 `NO_PROXY=127.0.0.1,localhost`

### Python
- 类型：新代码必须有类型注解（签名/返回值/核心结构）；尽量别用 `Any`
- 格式：行宽 120（`pyproject.toml` 的 ruff 配置）；black 运行时显式 `--line-length 120`
- 导入：标准库 -> 第三方 -> 本地；优先绝对导入；`sys.path.insert(...)` 仅限脚本入口/示例
- 异步：`async` 内不做阻塞 IO/`time.sleep`；需要时用 `asyncio.to_thread`/线程；`create_task` 要考虑异常记录与取消
- 日志：用 `logging.getLogger(__name__)`；异常用 `logger.exception(...)`；日志里不要打印 `api_key`/cookie 等敏感信息
- FastAPI：参数错误用 400/422；遇到 `HTTPException` 原样 `raise`；其它异常转换为 500（避免把敏感细节返回给客户端）
- 配置：通过 `system.config.config` 与 `system.config.get_server_port()`；读写 `config.json` 沿用 `charset_normalizer` + `json5`，写回尽量保留原编码（参考 `system/config_manager.py`）

#### FastAPI 错误处理模板（建议新端点沿用）
```python
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import HTTPException

logger = logging.getLogger(__name__)


async def handler(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        # ... validate / do work
        return {"ok": True}
    except HTTPException:
        raise
    except Exception:
        logger.exception("handler failed")
        raise HTTPException(status_code=500, detail="Internal error")
```

#### 配置项变更约定
- 新增/修改配置项：同时更新 `config.json.example`（并尽量给出注释/默认值）
- 不要在日志/异常里回显 `config.api.api_key`、cookie、token
- 写配置时尽量保持原文件编码与注释结构（仓库使用 `json5` 解析带注释 JSON）

### TypeScript/Vue（frontend/）
- 基线：`<script setup lang="ts">`；TS strict（见 `frontend/tsconfig*.json`），避免隐式 any
- 风格：2 空格缩进；字符串用单引号；默认不写分号；import 顺序 third-party -> 本地 -> 样式/虚拟模块（如 `virtual:uno.css`）
- 命名：组件 PascalCase；composable 用 `useXxx`
- 错误处理：外部资源初始化（Live2D/PIXI 等）必须 `try/catch`，用 `console.error` 带上下文

#### 前端构建/类型检查要点
- `npm run build` 会先跑 `vue-tsc -b`；类型错误应在这里被阻断
- 未配置 eslint/prettier：保持与已有文件一致即可（缩进/引号/分号尽量统一）

## 改动前快速自检
- 影响哪个服务边界（UI/apiserver/agentserver/mcpserver/voice）？
- 是否新增/修改配置项（需同步 `config.json.example`）？
- 是否引入阻塞/端口冲突/后台任务泄漏？
- 是否能用最小 pytest 或脚本复现验证？

## 测试新增建议（帮助后续单测运行）
- 新增 pytest：放在 `tests/`，文件名 `test_*.py`，函数名 `test_*`
- 异步测试：优先用 `pytest-asyncio`（仓库已在 dev 组中引入）
- 只需要“能跑起来”的回归：可以先用脚本式冒烟（`game/*_test.py`）再逐步迁移到 pytest

## 提交前自检（如果你要创建提交/PR）
- 至少跑一遍：`uv run ruff check .` + `uv run ruff format .`（必要时再跑 `uv run pytest`）
- 确认未提交敏感信息：尤其是 `config.json` 内的 `api_key`/cookie/token
- 新增配置项时同步更新：`config.json.example`
"""


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    return f"{NAGA_INTRO_CONTENT}"
