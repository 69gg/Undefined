from typing import Any, Dict

# NagaAgent 项目介绍内容（直接嵌入以保证稳定性）
NAGA_INTRO_CONTENT = """
# NagaAgent 项目上下文

## 项目概述

NagaAgent 是一个功能丰富的智能对话助手系统，采用多服务架构设计，提供智能对话、多Agent协作、知识图谱记忆、语音交互和现代化界面等核心功能。

### 核心特性

- **智能对话系统**：支持流式对话和工具调用循环
- **多Agent协作**：基于博弈论的智能任务调度
- **知识图谱记忆**：GRAG系统支持长期记忆和智能检索（基于Neo4j）
- **完整语音交互**：实时语音输入输出处理
- **现代化界面**：PyQt5 GUI + Live2D虚拟形象
- **系统托盘集成**：后台运行和快捷操作

## 技术架构

### 系统架构

项目采用微服务架构，主要包含以下独立服务：

1. **API服务器** (端口8000) - RESTful API接口
2. **Agent服务器** (端口8001) - 博弈论电脑控制智能体
3. **MCP服务器** (端口8003) - MCP工具调度服务
4. **TTS服务器** (端口5048) - 语音合成服务

### 技术栈

- **Python**: 3.11（推荐）
- **前端框架**: PyQt5 + Live2D + QSS
- **后端框架**: FastAPI + Uvicorn + AsyncIO
- **数据库**: Neo4j（知识图谱）
- **AI模型**: OpenAI兼容API + 通义千问
- **协议**: MCP (Model Context Protocol) + WebSocket + MQTT

### 依赖管理

- **主要依赖**: `nagaagent-core>=1.0.9`（核心依赖已整合）
- **包管理器**: `uv`（推荐）或 `pip`
- **配置文件**: `pyproject.toml` + `requirements.txt`

## 项目结构

```
NagaAgent/
├── main.py                    # 主入口文件
├── config.json.example        # 配置文件模板
├── setup.py / setup.sh        # 安装脚本
├── start.sh / start.bat       # 启动脚本
├── update.py                  # 更新脚本
│
├── apiserver/                 # API服务器模块
│   ├── api_server.py          # FastAPI应用
│   ├── llm_service.py         # LLM服务
│   ├── message_manager.py     # 消息管理器
│   └── streaming_tool_extractor.py # 流式工具提取器
│
├── agentserver/               # Agent服务器模块
│   ├── agent_server.py        # FastAPI应用
│   ├── agent_manager.py       # Agent管理器
│   ├── task_scheduler.py      # 任务调度器
│   ├── toolkit_manager.py     # 工具包管理器
│   └── agent_computer_control/ # 电脑控制智能体
│
├── mcpserver/                 # MCP服务器模块
│   ├── mcp_server.py          # FastAPI应用
│   ├── mcp_manager.py         # MCP管理器
│   ├── mcp_scheduler.py       # MCP调度器
│   ├── mcp_registry.py        # MCP注册中心
│   └── agent_*/               # 各种MCP工具代理
│
├── summer_memory/             # GRAG知识图谱记忆系统
│   ├── memory_manager.py      # 记忆管理器
│   ├── quintuple_extractor.py # 五元组提取器
│   ├── quintuple_graph.py     # 图数据库操作
│   ├── quintuple_rag_query.py # RAG查询
│   └── task_manager.py        # 任务管理器
│
├── game/                      # 多智能体博弈系统
│   ├── naga_game_system.py    # 博弈系统核心
│   ├── core/
│   │   ├── models/            # 数据模型
│   │   ├── interaction_graph/ # 交互图生成器
│   │   └── self_game/         # 自博弈模块
│   └── examples/              # 使用示例
│
├── ui/                        # PyQt5界面模块（MVC架构）
│   ├── pyqt_chat_window.py    # 主窗口
│   ├── components/            # UI组件
│   ├── controller/            # 控制器
│   ├── styles/                # 样式表
│   ├── live2d_local/          # Live2D虚拟形象
│   └── tray/                  # 系统托盘
│
├── voice/                     # 语音处理模块
│   ├── tts_wrapper.py         # TTS封装
│   ├── input/                 # 语音输入
│   └── output/                # 语音输出
│
├── system/                    # 系统配置和工具
│   ├── config.py              # 配置系统（Pydantic）
│   ├── config_manager.py      # 配置管理器
│   ├── system_checker.py      # 系统检测
│   └── background_analyzer.py # 后台分析器
│
├── mqtt_tool/                 # 物联网通讯工具
│   └── device_switch.py       # 设备控制
│
├── tests/                     # 测试用例
├── logs/                      # 日志目录
└── requirements.txt           # Python依赖
```

## 构建和运行

### 环境要求

- Python 3.11（推荐）
- 可选：uv工具（加速依赖安装）

### 安装依赖

**使用setup脚本（推荐）**:
```bash
# Linux/macOS
./setup.sh

# Windows
setup.bat
```

**手动安装**:
```bash
# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# 或
.\.venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 或使用uv
uv sync
```

### 配置

1. 复制配置文件模板：
```bash
cp config.json.example config.json
```

2. 编辑 `config.json`，配置LLM API：
```json
{
  "api": {
    "api_key": "你的api_key",
    "base_url": "模型服务商OPENAI API端点",
    "model": "模型名称"
  }
}
```

3. （可选）启用知识图谱记忆：
```json
{
  "grag": {
    "enabled": true,
    "neo4j_uri": "neo4j://127.0.0.1:7687",
    "neo4j_user": "neo4j",
    "neo4j_password": "你安装neo4j时设置的密码"
  }
}
```

### 启动应用

**使用启动脚本**:
```bash
# Linux/macOS
./start.sh

# Windows
start.bat
```

**直接运行**:
```bash
# 激活虚拟环境后
python main.py

# 或使用uv
uv run main.py
```

### 系统检测

```bash
# 完整环境检测
python main.py --check-env

# 快速检测
python main.py --quick-check

# 强制检测（忽略缓存）
python main.py --check-env --force-check
```

### 更新

```bash
# 使用更新脚本
./update.sh         # Linux/macOS
update.bat          # Windows

# 或直接运行
python update.py
```

## 开发规范

### 代码风格

- **Python版本**: 3.11+
- **类型注释**: 使用类型提示（typing模块）
- **代码格式**: 建议使用black（行长度120字符）
- **代码检查**: 建议使用ruff
- **日志级别**: INFO（开发时可设为DEBUG）

### 架构设计

1. **模块化设计**: 各服务独立运行，支持热插拔
2. **配置驱动**: 实时配置热更新，无需重启
3. **异步优先**: 使用AsyncIO进行异步处理
4. **类型安全**: 使用Pydantic进行数据验证

### UI开发规范

- **MVC架构**: UI组件符合MVC结构
- **组件化**: 先创建widget组件和工具，验证后再集成到window
- **线程安全**: 跨线程调用Qt需使用信号槽机制
- **样式管理**: 使用QSS统一样式

### 配置管理

- **配置文件**: `config.json`（支持注释，使用json5解析）
- **配置类**: `system/config.py` 中的Pydantic模型
- **热更新**: 支持配置变更监听和通知

### 日志规范

- **日志目录**: `logs/`
- **日志级别**: DEBUG, INFO, WARNING, ERROR, CRITICAL
- **日志格式**: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`

### 测试

- **测试框架**: pytest
- **测试目录**: `tests/`
- **异步测试**: pytest-asyncio

## 关键端口

- **API服务器**: 8000
- **Agent服务器**: 8001
- **MCP服务器**: 8003
- **TTS服务器**: 5048
- **ASR服务器**: 5060

## 重要注意事项

1. **Python版本**: 必须使用Python 3.11，其他版本可能不兼容
2. **端口占用**: 启动前确保端口8000、8001、8003、5048未被占用
3. **Neo4j连接**: 如果启用GRAG，确保Neo4j服务正在运行
4. **编码问题**: 配置文件使用UTF-8编码，支持中文
5. **虚拟环境**: 建议使用虚拟环境隔离依赖
6. **系统检测**: 首次启动会自动进行系统环境检测

## 故障排除

1. **Python版本不兼容**: 确保使用Python 3.11
2. **端口被占用**: 检查并释放相关端口
3. **Neo4j连接失败**: 检查Neo4j服务状态和连接配置
4. **依赖安装失败**: 尝试使用uv代替pip
5. **UI显示异常**: 检查PyQt5和OpenGL依赖

## 扩展开发

### 添加新的MCP工具

1. 在 `mcpserver/agent_*/` 创建新的MCP代理目录
2. 实现 `mcp_tools.py` 定义工具接口
3. 在 `mcpserver/mcp_registry.py` 注册新工具

### 添加新的UI组件

1. 在 `ui/components/` 创建组件文件
2. 遵循MVC架构，分离视图和逻辑
3. 在 `ui/pyqt_chat_window.py` 中集成组件

### 扩展博弈系统

1. 在 `game/core/` 添加新模块
2. 使用 `game/core/models/` 中的数据模型
3. 在 `game/examples/` 添加使用示例

## 许可证

MIT License - 详见 LICENSE 文件

## 贡献指南

欢迎创建Issue和Pull Request！

- 遵循现有代码风格
- 添加必要的类型注释
- 编写清晰的提交信息
- 更新相关文档
"""


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    return f"NagaAgent 项目介绍文档:\n\n{NAGA_INTRO_CONTENT}"
