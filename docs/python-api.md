# Python 库 API 参考

Undefined 可作为 Python 库嵌入到其他应用、脚本或测试环境中，复用配置系统、AI 客户端、Skills 注册表、认知记忆、知识库等组件，而无需启动完整的 QQ Bot CLI。

> CLI 入口（`Undefined` / `Undefined-webui`）行为不变；库嵌入路径与 CLI 启动链隔离。详见 [配置详解 — 库嵌入配置](configuration.md#2-库嵌入配置)。

---

## 安装

```bash
# 源码开发
uv sync

# 或 PyPI 包
pip install Undefined-bot
```

Python 版本要求：`3.11` ~ `3.13`。

包内附带 [`py.typed`](../src/Undefined/py.typed) 标记，mypy / Pyright / IDE 可直接消费类型信息。

---

## 推荐 import 路径

### 根包（`stable`，lazy re-export）

以下符号承诺通过 `from Undefined import …` 长期稳定（完整清单见下文 [公共 API 符号表](#公共-api-符号表)）：

```python
from Undefined import (
    __version__,
    Config,
    get_config,
    set_config,
    AIClient,
    ToolRegistry,
    AgentRegistry,
    PipelineRegistry,
    BaseRegistry,
    AnthropicSkillRegistry,
    CognitiveService,
    KnowledgeManager,
    MemeService,
    AttachmentRegistry,
    RuntimeAPIServer,
    RuntimeAPIContext,
)
```

根包符号与 [公共 API 符号表](#公共-api-符号表) 一致；若需更细粒度导入，可使用下方子包路径，二者语义等价。

### 子包（`stable` / `subpackage`）

| 稳定性 | 模块 | 常用符号 |
|--------|------|----------|
| stable | `Undefined.config` | `Config`, `get_config`, `set_config`, `ConfigBuilder`, `ChatModelConfig`, `VisionModelConfig`, … |
| stable | `Undefined.ai` | `AIClient` |
| stable | `Undefined.skills` | `ToolRegistry`, `AgentRegistry`, `PipelineRegistry` |
| stable | `Undefined.cognitive` | `CognitiveService`, `CognitiveVectorStore`, `ProfileStorage`, … |
| stable | `Undefined.knowledge` | `KnowledgeManager`, `Embedder`, `Reranker`, `RetrievalRuntime` |
| stable | `Undefined.memes` | `MemeService`, `MemeStore`, `MemeWorker`, … |
| stable | `Undefined.attachments` | `AttachmentRegistry` |
| stable | `Undefined.api` | `RuntimeAPIServer`, `RuntimeAPIContext` |
| subpackage | `Undefined.skills.registry` | `BaseRegistry`, `SkillItem`, `SkillStats` |
| subpackage | `Undefined.skills.anthropic_skills` | `AnthropicSkillRegistry` |
| subpackage | `Undefined.mcp` | `MCPToolRegistry`, `MCPToolSetRegistry` |

### 向后兼容 shim 路径

拆分后旧路径仍可用（测试与下游代码可继续引用）：

```python
from Undefined.config.loader import Config          # → Undefined.config.Config
from Undefined.ai.client import AIClient
from Undefined.attachments import AttachmentRegistry
from Undefined.skills.tools import ToolRegistry
from Undefined.cognitive.service import CognitiveService
from Undefined.knowledge.manager import KnowledgeManager
from Undefined.memes.service import MemeService
from Undefined.api.app import RuntimeAPIServer
```

拆分后的各模块旁保留 compatibility shim 文件，旧 import 路径仍可用（见各 shim 文件顶部的 re-export）。

### 内部模块（不承诺稳定）

以下模块**不会**进入根包 re-export，也不保证跨版本兼容：

- `Undefined.main`, `Undefined.webui`, `Undefined.handlers`, `Undefined.onebot`
- `Undefined.config.coercers`, `Undefined.config.model_parsers`
- `Undefined.utils.io`, `Undefined.utils.paths`

---

## 配置 API

库嵌入场景的核心入口是 `Config.from_mapping()` 与 opt-in 的 `set_config()`。

### 加载优先级

```
Python 显式 mapping / override  >  config.toml  >  环境变量  >  代码默认值
```

- `Config.from_mapping()` / `Config.builder()`：**不读取** `config.toml`，适合测试与无文件部署。
- `Config.load()`：从指定或 CWD 下的 `config.toml` 加载（CLI 路径）。
- 环境变量仅在 TOML / mapping **未提供**对应项时兜底；详见 [配置详解 — 环境变量兜底](configuration.md#8-环境变量兜底迁移建议)。

### `Config.from_mapping`

从内存 dict 构建配置，结构与 `config.toml` 一致：

```python
from Undefined.config import Config

cfg = Config.from_mapping(
    {
        "core": {"bot_qq": 123456, "superadmin_qq": 654321},
        "onebot": {"ws_url": "ws://127.0.0.1:3001"},
        "models": {
            "chat": {
                "api_url": "https://api.example/v1",
                "api_key": "sk-xxx",
                "model_name": "gpt-4o-mini",
            },
            "vision": {
                "api_url": "https://api.example/v1",
                "api_key": "sk-xxx",
                "model_name": "gpt-4o-mini",
            },
            "agent": {
                "api_url": "https://api.example/v1",
                "api_key": "sk-xxx",
                "model_name": "gpt-4o-mini",
            },
        },
    },
    strict=False,  # 库嵌入 / 测试可放宽；生产 Bot 建议 strict=True
)

print(cfg.chat_model.model_name)  # gpt-4o-mini
```

`strict=True` 时缺失必填项（如 `onebot.ws_url`、各模型 `api_url` 等）会抛出异常；行为与 CLI 严格模式一致。

### `Config.builder`

链式构建器，适合在 base mapping 上覆盖少量字段：

```python
cfg = (
    Config.builder()
    .with_mapping({"onebot": {"ws_url": "ws://127.0.0.1:3001"}, "models": {...}})
    .override(log_level="DEBUG")
    .build(strict=False)
)
```

### `set_config`（opt-in 单例注入）

将已构建的 `Config` 注入全局单例，供 `get_config()` 读取：

```python
from Undefined.config import Config, get_config, set_config

cfg = Config.from_mapping({...}, strict=False)
set_config(cfg)

assert get_config(strict=False) is cfg
```

**约束**：

- `set_config()` 仅供库嵌入 opt-in 使用；**CLI / WebUI 启动链不得调用**。
- 未调用 `set_config()` 时，`get_config()` 仍走 CWD 下 `./config.toml`（与 CLI 行为一致）。

### 纯环境变量构建

mapping 为空时，已注册的环境变量仍可兜底填充配置：

```python
import os

os.environ["ONEBOT_WS_URL"] = "ws://127.0.0.1:3001"
os.environ["CHAT_MODEL_API_URL"] = "https://api.example/v1"
# ... 其他必填 env

cfg = Config.from_mapping({}, strict=False)
```

完整 env 注册表见 [配置详解 §8](configuration.md#8-环境变量兜底迁移建议)。

---

## 典型嵌入示例

### 单元测试

```python
from Undefined.config import Config, set_config

@pytest.fixture
def app_config():
    cfg = Config.from_mapping(MINIMAL_MAPPING, strict=False)
    set_config(cfg)
    yield cfg
```

### 脚本中复用 AIClient

```python
from Undefined.config import Config
from Undefined.ai.client import AIClient

cfg = Config.from_mapping({...}, strict=False)
client = AIClient(cfg)
# 使用 client 发起 LLM 请求 …
```

### 挂载 Runtime API

```python
from Undefined.config import Config, set_config
from Undefined.api import RuntimeAPIServer, RuntimeAPIContext

cfg = Config.from_mapping({...}, strict=True)
set_config(cfg)
server = RuntimeAPIServer(RuntimeAPIContext(...))
```

---

## 公共 API 符号表

根包与子包 `__all__` 中列出的符号为稳定面；semver minor 内不 breaking。

### 根包 re-export（`stable`）

| 符号 | 定义模块 | 说明 |
|------|----------|------|
| `__version__` | `Undefined` | 包版本 |
| `Config` | `Undefined.config` | 应用配置 dataclass |
| `get_config` | `Undefined.config` | 获取全局配置单例 |
| `set_config` | `Undefined.config` | opt-in 注入 Config（CLI 不调用） |
| `Config.builder` | `Undefined.config` | 链式配置构建器 |
| `Config.from_mapping` | `Undefined.config` | 从 dict 构建配置 |
| `AIClient` | `Undefined.ai` | LLM 请求客户端 |
| `ToolRegistry` | `Undefined.skills` | 工具注册表 |
| `AgentRegistry` | `Undefined.skills` | Agent 注册表 |
| `PipelineRegistry` | `Undefined.skills` | 自动处理管线注册表 |
| `BaseRegistry` | `Undefined.skills.registry` | 注册表基类 |
| `AnthropicSkillRegistry` | `Undefined.skills.anthropic_skills` | Anthropic Skills 注册表 |
| `CognitiveService` | `Undefined.cognitive` | 认知记忆服务 |
| `KnowledgeManager` | `Undefined.knowledge` | 本地知识库管理 |
| `MemeService` | `Undefined.memes` | 表情包库服务 |
| `AttachmentRegistry` | `Undefined.attachments` | 附件 UID 登记 |
| `RuntimeAPIServer` | `Undefined.api` | 主进程 Runtime API 服务 |
| `RuntimeAPIContext` | `Undefined.api` | Runtime API 运行时上下文 |

### 子包公开面

| 包 | 稳定性 | 符号 |
|----|--------|------|
| `Undefined.config` | stable | `Config`, `get_config`, `get_config_manager`, `set_config`, `WebUISettings`, `load_webui_settings`, `ChatModelConfig`, `VisionModelConfig`, `SecurityModelConfig`, `APIConfig`, `AgentModelConfig`, `EmbeddingModelConfig`, `GrokModelConfig`, `RerankModelConfig`, `ModelPool`, `ModelPoolEntry`, `MemeConfig`, `MessageBatcherConfig`, `RenderCacheConfig` |
| `Undefined.ai` | stable | `AIClient` |
| `Undefined.skills` | stable | `ToolRegistry`, `AgentRegistry`, `PipelineRegistry` |
| `Undefined.skills.registry` | subpackage | `BaseRegistry`, `SkillItem`, `SkillStats`, `RegistryExecutionTimeoutError` |
| `Undefined.skills.anthropic_skills` | subpackage | `AnthropicSkillRegistry` |
| `Undefined.skills.pipelines` | subpackage | `PipelineRegistry`, `PipelineDetection` |
| `Undefined.cognitive` | stable | `CognitiveService`, `CognitiveVectorStore`, `ProfileStorage`, `HistorianWorker`, `JobQueue` |
| `Undefined.knowledge` | stable | `KnowledgeManager`, `Embedder`, `Reranker`, `RetrievalRuntime` |
| `Undefined.memes` | stable | `MemeService`, `MemeStore`, `MemeWorker`, `MemeVectorStore`, `MemeRecord`, `MemeSearchItem`, `MemeSourceRecord` |
| `Undefined.attachments` | stable | `AttachmentRegistry` |
| `Undefined.api` | stable | `RuntimeAPIServer`, `RuntimeAPIContext` |
| `Undefined.mcp` | subpackage | `MCPToolRegistry`, `MCPToolSetRegistry` |

---

## 相关文档

- [配置详解](configuration.md) — TOML 字段、热更新、库嵌入（§2）、环境变量全表（§8）
- [安装与部署](deployment.md) — CLI 部署与库嵌入交叉引用
- [Runtime API / OpenAPI](openapi.md) — HTTP 集成
- [开发者与拓展中心](development.md) — 源码结构与自检命令
