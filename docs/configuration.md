# 配置详解（`config.toml`）

本文档是 Undefined 当前配置系统的完整说明，覆盖：
- 配置加载顺序与解析规则
- **库嵌入**（`Config.from_mapping` / `set_config`）程序化配置
- 严格模式必填项
- 每个配置节与字段的用途、默认值、约束、回退行为
- 热更新与重启生效边界
- 兼容旧字段与环境变量迁移建议

建议搭配 [config.toml.example](../config.toml.example) 一起阅读。

---

## 1. 配置文件与加载机制

### 1.1 主配置文件
- 主文件：`config.toml`
- 示例模板：`config.toml.example`
- 启动 WebUI 时，如 `config.toml` 不存在，会自动用示例模板生成。
- 已有 `config.toml` 想补齐新增配置项/注释时，可用 WebUI 的“同步模板”按钮，或运行 `python scripts/sync_config_template.py`（也支持 `uv run python scripts/sync_config_template.py`）。

### 1.2 运行时本地文件
- `config.local.json`：运行时维护的本地管理员列表（如 `/admin add`）。
- 该文件会与 `core.admin_qq` 合并。
- 该文件也在热更新监听范围内。

### 1.3 加载优先级
1. `config.toml` 中的显式值
2. 对应环境变量（仅当 TOML 该项缺失时兜底）
3. 代码默认值

说明：检测到环境变量兜底时会输出告警，建议迁移到 `config.toml` 统一管理。

### 1.4 解析与归一化规则
- 读取编码：`utf-8-sig`。
- 字符串：会做 `strip()`，空字符串通常视为未配置。
- 整数/浮点：非法值回退默认值。
- 布尔：支持 `true/false`、`1/0`、`yes/no`、`on/off`。
- URL 基址：`api_endpoints.*_base_url` 会自动去掉末尾 `/`。
- TOML 解析错误会给出具体行列、问题行和 Windows 路径提示。

---

## 2. 库嵌入配置

除 CLI / WebUI 从 CWD 读取 `config.toml` 外，Undefined 支持在 Python 代码中**程序化构建配置**，供测试、脚本或其它应用嵌入库组件时使用。

> 完整 API 说明见 [Python 库 API 参考](python-api.md)。

### 2.1 适用场景

- 单元测试 / 集成测试：无需准备真实 `config.toml`
- 下游应用：只复用 `AIClient`、`KnowledgeManager` 等模块，不启动 QQ Bot
- CI / 容器：通过环境变量 + 空 mapping 注入密钥，配置文件只保留非敏感项

### 2.2 加载优先级

```
Python 显式 mapping / builder.override  >  config.toml  >  环境变量  >  代码默认值
```

| 入口 | 是否读 `config.toml` | 说明 |
|------|---------------------|------|
| `Config.load()` | 是 | CLI / WebUI 默认路径 |
| `Config.from_mapping(dict)` | 否 | 纯内存构建 |
| `Config.builder().with_mapping(...).build()` | 否 | 在 mapping 上链式覆盖 |
| `get_config()` | 视情况 | 未 `set_config()` 时等价于 `Config.load()` |

`from_mapping` / `builder` 仍会读取进程环境变量中**已注册**的兜底项（TOML / mapping 未提供的字段）。注册表见 [`env_registry.py`](../src/Undefined/config/env_registry.py) 与本文 [§8 环境变量兜底](#8-环境变量兜底迁移建议)。

### 2.3 `Config.from_mapping`

结构与 `config.toml` 一致，例如：

```python
from Undefined.config import Config

cfg = Config.from_mapping(
    {
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
    strict=False,
)
```

- `strict=True`：与 CLI 相同，缺失 [§3 严格模式](#3-严格模式stricttrue必填项) 必填项时报错退出。
- `strict=False`：适合测试与渐进式嵌入；生产 Bot 仍建议 `strict=True`。

### 2.4 `Config.builder`

```python
cfg = (
    Config.builder()
    .with_mapping(base_mapping)
    .override(log_level="DEBUG")
    .build(strict=False)
)
```

`override()` 目前覆盖 mapping 顶层键；嵌套结构请直接在 `with_mapping` 的 dict 中提供。

### 2.5 `set_config()`（opt-in）

```python
from Undefined.config import Config, get_config, get_config_manager, set_config

cfg = Config.from_mapping({...}, strict=False)
set_config(cfg)
assert get_config(strict=False) is cfg
assert get_config_manager().load(strict=False) is cfg
```

**硬约束**：

- `set_config()` 仅供库嵌入 opt-in；**CLI / WebUI 启动链不得调用**。
- 未调用 `set_config()` 时，`get_config()` 仍从 CWD 加载 `./config.toml`，与独立运行 Bot 行为一致。
- 调用 `set_config()` 会同步更新 `get_config()` 与 `get_config_manager().load()` 的缓存，避免双轨读到不同实例。

---

## 3. 严格模式（`strict=True`）必填项

程序主流程使用严格模式加载配置。缺失以下字段会报错退出：
- `core.bot_qq`
- `core.superadmin_qq`
- `onebot.ws_url`
- `models.chat.api_url` / `api_key` / `model_name`
- `models.vision.api_url` / `api_key` / `model_name`
- `models.agent.api_url` / `api_key` / `model_name`
- 若 `knowledge.enabled=true`，还必须配置：`models.embedding.api_url` / `model_name`

> 注意：`cognitive.enabled=true` 时如果 embedding 未配置，不会直接抛错退出，而是启动时自动降级禁用认知记忆并打印告警。

---

## 4. 最小可运行配置示例

```toml
[core]
bot_qq = 123456
superadmin_qq = 654321

[onebot]
ws_url = "ws://127.0.0.1:3001"
token = ""

[models.chat]
api_url = "https://api.openai.com/v1"
api_key = "sk-xxx"
model_name = "gpt-4o-mini"

[models.vision]
api_url = "https://api.openai.com/v1"
api_key = "sk-xxx"
model_name = "gpt-4o-mini"

[models.agent]
api_url = "https://api.openai.com/v1"
api_key = "sk-xxx"
model_name = "gpt-4o-mini"
```

---

## 5. 全量字段说明

### 4.1 `[core]` 机器人核心行为

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `bot_qq` | `0` | 机器人 QQ 号 | `>0` 才合法（严格模式必填） |
| `superadmin_qq` | `0` | 超级管理员 QQ | `>0` 才合法（严格模式必填） |
| `admin_qq` | `[]` | 初始管理员列表 | 与 `config.local.json` 中动态管理员合并 |
| `forward_proxy_qq` | `0` | 音频转发代理 QQ（可选） | `<=0` 视为 `None` |
| `process_every_message` | `true` | 群聊是否处理每条消息 | 关闭后仅处理 @ 触发 |
| `process_private_message` | `true` | 是否处理私聊回复 | 关闭后私聊只记录历史，不回复 |
| `process_poke_message` | `true` | 是否响应拍一拍 | 关闭后忽略 poke |
| `context_recent_messages_limit` | `20` | 注入到提示词的最近历史条数 | `<0` 视为 `0`（关闭注入）；无固定上限，受 `max_records` 与存储约束 |
| `ai_request_max_retries` | `2` | 单次 LLM 请求失败重试次数 | `<0` 自动回退到 `0`；支持热更新 |
| `missing_tool_call_retries` | `3` | 模型返回纯文本但未调用任何工具时的纠正重试次数（保留 assistant 纯文本 + 通用纠正提示，不写死具体 tool） | `<0` 自动回退到 `0`；支持热更新 |

---

### 4.2 `[access]` 访问控制

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `mode` | `"off"` | 模式：`off` / `blacklist` / `allowlist` | 非法值回退 `off` |
| `allowed_group_ids` | `[]` | 群白名单 | `allowlist` 模式生效 |
| `blocked_group_ids` | `[]` | 群黑名单 | `blacklist` 模式生效（优先） |
| `allowed_private_ids` | `[]` | 私聊白名单 | `allowlist` 模式生效 |
| `blocked_private_ids` | `[]` | 私聊黑名单 | `blacklist` 模式生效 |
| `superadmin_bypass_allowlist` | `true` | 超管私聊是否绕过私聊白名单 | 仅私聊，不影响群 |
| `superadmin_bypass_private_blacklist` | `false` | 超管私聊是否绕过私聊黑名单 | 仅私聊 |

补充：
- 若 `access.mode` 未设置，但任一名单非空，会进入兼容模式 `legacy`（黑白名单联动）；建议显式设置 `mode`。
- `blocked_*` 优先于 `allowed_*`。

---

### 4.3 `[onebot]` 协议端连接

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `ws_url` | `""` | OneBot WebSocket 地址 | 模板示例通常写 `ws://127.0.0.1:3001`；严格模式必填 |
| `token` | `""` | OneBot token | 同时用于 URL 参数与 `Authorization` 头 |

`onebot.*` 变更需要重启进程才能生效。

---

### 4.4 `[models]` 模型配置总览

### 4.4.1 生成模型通用字段

| 字段 | 含义 |
|---|---|
| `api_url` | Provider 基址；OpenAI 兼容接口通常为 `.../v1`，Anthropic 原生接口可写站点根地址或 `.../v1` |
| `api_key` | API Key |
| `model_name` | 模型名 |
| `max_tokens` | 最大输出 token；OpenAI 模式下设为 `0` 或负数时不发送上限字段，Anthropic Messages 要求为正整数 |
| `context_window_tokens` | 模型上下文窗口上限（token），用于 `/summary` 分块与 Prompt 预算；解析默认 `8192`，须按上游模型能力配置 |
| `queue_interval_seconds` | 该模型请求队列发车间隔（秒，`0` 表示立即发车） |
| `use_proxy` | 是否让该模型请求使用 `[proxy]` 中配置的代理地址；默认 `false`，各模型种类独立配置 |
| `api_mode` | `openai.chat_completions`、`openai.responses` 或 `anthropic.messages`；旧 `chat_completions` / `responses` 仍兼容但会告警 |
| `reasoning_enabled` | 是否发送当前 API mode 对应的 effort 参数 |
| `reasoning_effort` | 自定义 effort 字符串；`adaptive` 原样发送，其余值也不做枚举或大小写改写 |
| `thinking_param_enabled` | 是否发送由 `thinking_enabled` 自动生成的顶层 `thinking` 参数；默认 `true`，不影响 effort 或调用方显式传入的 `thinking` |
| `thinking_enabled` | 是否启用旧式 `thinking` 参数 |
| `thinking_budget_tokens` | thinking 预算 |
| `thinking_include_budget` | 是否发送手动 `budget_tokens`；`anthropic.messages` 下关闭时使用 adaptive thinking |
| `thinking_tool_call_compat` | 是否在本地历史保留兼容的可读 `reasoning_content`；默认 `true` |
| `reasoning_content_replay` | 是否向上游原样回传推理载体；覆盖 Chat 兼容字段、Responses reasoning items / encrypted content、Anthropic thinking / redacted blocks；默认 `true` |
| `system_prompt_as_user` | 是否将所有 `system`/`developer` 消息合并注入首条 `user`（仅 `openai.chat_completions`）；默认 `false` |
| `responses_tool_choice_compat` | `responses` 下的 `tool_choice` 兼容开关：仅建议在默认关闭时请求仍返回 500、怀疑上游不兼容对象型 `tool_choice` 时再尝试开启；开启后降级为字符串 `"required"`；默认 `false` |
| `responses_force_stateless_replay` | `responses` 下的续轮强制降级开关：启用后多轮工具调用始终跳过 `previous_response_id`，改为完整消息重放；默认 `false` |
| `prompt_cache_enabled` | OpenAI 模式下是否自动生成稳定的 `prompt_cache_key`；Anthropic 模式不发送该字段；默认 `true` |
| `request_params` | 额外请求体参数（透传给模型 API，保留字段会忽略） |

请求模式说明：
- `api_mode="openai.chat_completions"`：走 `AsyncOpenAI.chat.completions.create(...)`
  - `max_tokens > 0` 时发送 `max_tokens`；为 `0` 或负数时省略
  - `thinking_enabled=true` 且 `thinking_param_enabled=true` 时发送兼容接口常用的顶层 `thinking`
  - `reasoning_enabled=true` 时发送顶层 `reasoning_effort="..."`
  - 回放开启时优先恢复响应原始字段：`reasoning_content`、`reasoning_details`、`reasoning`、`encrypted_content`、`thinking`；OpenRouter 的 `reasoning_details` 数组、签名与密文保持原顺序和原值
  - 旧历史没有原始载体时，才回退到可读 `reasoning_content`
- `api_mode="openai.responses"`：走 `AsyncOpenAI.responses.create(...)`
  - `max_tokens > 0` 时映射为 `max_output_tokens`；为 `0` 或负数时省略
  - `thinking_enabled=true` 且 `thinking_param_enabled=true` 时发送兼容接口使用的顶层 `thinking`
  - `reasoning_enabled=true` 时发送 `reasoning.effort`；`request_params.reasoning` 的 `summary` 等其他键会保留并与 effort 合并
  - 若 `request_params` 里带 `response_format` / `verbosity`，会自动映射到 `text.format` / `text.verbosity`
  - 默认使用官方对象格式：`{"type":"function","name":"..."}`
  - `responses_tool_choice_compat=true` 时，会把指定函数的 `tool_choice` 降级为字符串 `"required"`，并只保留目标工具，用于兼容部分不完整代理
  - 默认使用 `previous_response_id + function_call_output` 增量续轮，并在每轮重新发送当前 `instructions`
  - `responses_force_stateless_replay=true` 时跳过 `previous_response_id`，按历史顺序回放原始 `output` items；推理回放开启时自动请求并回放 `reasoning.encrypted_content`
  - SDK 展开的 `function_call.id=null` / `namespace=null` 只在 function call replay item 上定向删除；真实 `fc_*` id、非空 namespace 与其他显式 null 不做全局清洗
  - Responses 工具续轮遵循 OpenAI 的标准字段语义：工具结果使用 `function_call_output.call_id` 关联前一轮工具调用；`function_call.id` 若存在，必须是模型生成的 output item id（通常为 `fc_*`），不能把 `call_*` 误写进 `id`
  - 仅建议在默认关闭时请求仍返回 500，再尝试开启这些兼容开关
  - 当前已知 `new-api v0.11.4-alpha.3` 存在这类兼容问题
- `api_mode="anthropic.messages"`：走 `AsyncAnthropic.messages.create(...)` / `messages.stream(...)`
  - 官方 Messages API 将 `max_tokens` 定义为必填字段；运行时要求其为正整数并原样发送，`0` 或负数会在请求发出前报错
  - 自动转换顶层 `system`、图片、函数工具、`tool_use` / `tool_result`，不使用手写 HTTP 请求
  - `thinking_enabled=true`、`thinking_param_enabled=true` 且 `thinking_include_budget=true` 时发送 `thinking={type="enabled", budget_tokens=...}`；预算必须 `>=1024` 且严格小于本次 `max_tokens`
  - `thinking_enabled=true`、`thinking_param_enabled=true` 且 `thinking_include_budget=false` 时发送 `thinking={type="adaptive"}`
  - `reasoning_enabled=true` 时发送 `output_config.effort`，值按 `reasoning_effort` 原样透传；其他 `output_config` 键继续保留
  - 回放开启时按原顺序发送完整 `thinking` / `redacted_thinking` / `text` / `tool_use` blocks；关闭时只过滤 thinking 与 redacted blocks
  - Anthropic thinking 开启时不支持强制指定工具，强制 `tool_choice` 会降级为 `auto`

Prompt caching 补充：
- `openai.chat_completions` / `openai.responses` 下，当 `prompt_cache_enabled=true` 且未显式设置 `prompt_cache_key` 时，运行时会按“模型名 + call_type + 会话作用域”自动生成稳定 key。
- `anthropic.messages` 不发送 OpenAI 的 `prompt_cache_key`；需要 Anthropic prompt caching 时，通过 `request_params.cache_control` 配置官方 `cache_control`。
- 该 key 只用于提升路由稳定性，不改变 prompt 内容。
- 想提高缓存命中率时，仍应尽量把静态内容放前面、把高频变化内容放后面。

`request_params` 说明：
- 适合放 provider 私有请求体字段，例如 `metadata`、`temperature`、兼容网关扩展参数等。
- `reasoning_effort` 与 `thinking` 由正式配置字段控制，`request_params` 中的同名保留字段不能覆盖；兼容 Chat 的 `reasoning` 对象、Responses 的 `reasoning.summary` 等附加键、Anthropic 的其他 `output_config` 键属于明确的合并例外，专用 effort 配置优先。
- `thinking_param_enabled=false` 只禁止根据 `thinking_enabled` 自动生成参数。代码调用方通过单次请求参数显式传入的 `thinking` 仍会发送；`reasoning_enabled` / `reasoning_effort` 完全独立，不受该开关影响。
- 消息总结分块读取 `[models.summary].context_window_tokens`（未单独配置时回退 `[models.agent]`）；不再使用硬编码窗口或 `request_params` 里的 `context_length` 类字段。

#### 思维链续传迁移说明

旧文档曾将 `thinking_tool_call_compat=true` 描述为“向上游回传 `reasoning_content`”。当前实现已拆分为两个独立开关：

| 开关 | 作用 |
|------|------|
| `thinking_tool_call_compat=true`（默认） | 在本地历史保留兼容的可读 `reasoning_content`，供日志与旧历史回退 |
| `reasoning_content_replay=true`（默认） | 优先原样回传当前有效历史中的全部原生推理结构；旧历史缺少原始结构时才回退 `reasoning_content` |

**升级建议**：
- 若不希望向上游发送任何明文、summary、签名或加密推理材料，请在对应模型节显式设置 `reasoning_content_replay = false`。
- MiMo / DeepSeek 等兼容接口通常使用 `api_mode = "openai.chat_completions"`；Responses 兼容网关仅在状态续轮不可用时再开启 `responses_force_stateless_replay`。

兼容字段（旧配置）：
- `models.<x>.deepseek_new_cot_support`
  - 若开启：等效默认 `thinking_include_budget=false` + `thinking_tool_call_compat=true`
  - 显式设置新字段时，以新字段为准。

### 4.4.2 `[models.chat]` 主对话模型

默认：
- `max_tokens=8192`
- `queue_interval_seconds=1.0`（`0` 表示立即发车，`<0` 回退 `1.0`）
- `api_mode="openai.chat_completions"`
- `reasoning_enabled=false`
- `reasoning_effort="medium"`
- `thinking_param_enabled=true`
- `thinking_budget_tokens=20000`
- `thinking_tool_call_compat=true`
- `reasoning_content_replay=true`
- `responses_tool_choice_compat=false`
- `responses_force_stateless_replay=false`
- `use_proxy=false`

补充：
- 若上游只提供 `/v1/responses`，可将 `api_mode` 切到 `openai.responses`。
- `[models.chat.request_params]` 可放 `temperature`、`response_format`、`verbosity`、兼容网关 `reasoning` 对象或其他私有字段。

### 4.4.3 `[models.vision]` 视觉模型

默认：
- `queue_interval_seconds=1.0`（`0` 表示立即发车，`<0` 回退 `1.0`）
- `api_mode="openai.chat_completions"`
- `reasoning_enabled=false`
- `reasoning_effort="medium"`
- `thinking_param_enabled=true`
- `thinking_budget_tokens=20000`
- `thinking_tool_call_compat=true`
- `reasoning_content_replay=true`
- `responses_tool_choice_compat=false`
- `responses_force_stateless_replay=false`
- `use_proxy=false`

### 4.4.4 `[models.security]` 安全模型

字段：
- 额外开关：`enabled=true`
- 默认：`max_tokens=100`、`queue_interval_seconds=1.0`（`0` 表示立即发车，`<0` 回退 `1.0`）、`api_mode="openai.chat_completions"`、`reasoning_enabled=false`、`reasoning_effort="medium"`、`thinking_param_enabled=true`、`thinking_budget_tokens=0`、`thinking_tool_call_compat=true`、`reasoning_content_replay=true`、`responses_tool_choice_compat=false`、`responses_force_stateless_replay=false`、`use_proxy=false`

关键回退逻辑：
- 若 `api_url/api_key/model_name` 任一缺失，会自动回退为 chat 模型（并告警）。
- 回退时会继承 chat 的 `api_mode`、`reasoning_*`、`thinking_param_enabled`、`responses_tool_choice_compat`、`responses_force_stateless_replay` 与 `request_params`；其余旧 `thinking_*` 仍保持安全模型自身默认值；`use_proxy` 仍只读取 `[models.security]` 自身配置，默认 `false`。

### 4.4.5 `[models.naga]` Naga 审核模型

用途：
- 仅用于 `POST /api/v1/naga/messages/send` 前的消息审核。

默认：
- `max_tokens=160`
- `queue_interval_seconds=1.0`（`0` 表示立即发车，`<0` 回退 `1.0`）
- `api_mode="openai.chat_completions"`
- `reasoning_enabled=false`
- `reasoning_effort="medium"`
- `thinking_param_enabled=true`
- `thinking_enabled=false`
- `thinking_budget_tokens=0`
- `thinking_include_budget=true`
- `thinking_tool_call_compat=true`
- `reasoning_content_replay=true`
- `responses_tool_choice_compat=false`
- `responses_force_stateless_replay=false`
- `use_proxy=false`

关键回退逻辑：
- 若整个节缺失或 `api_url/api_key/model_name` 任一缺失：完整回退到 `models.security`，并沿用安全模型的请求参数；`use_proxy` 仍只读取 `[models.naga]` 自身配置，默认 `false`。

### 4.4.6 `[models.agent]` Agent 执行模型

默认：
- `max_tokens=4096`
- `queue_interval_seconds=1.0`（`0` 表示立即发车，`<0` 回退 `1.0`）
- `api_mode="openai.chat_completions"`
- `reasoning_enabled=false`
- `reasoning_effort="medium"`
- `thinking_param_enabled=true`
- `thinking_tool_call_compat=true`
- `reasoning_content_replay=true`
- `responses_tool_choice_compat=false`
- `responses_force_stateless_replay=false`
- `use_proxy=false`

### 4.4.7 `[models.historian]` 史官模型

- 用于认知记忆后台改写。
- 若整个节缺失或为空：完整回退到 `models.agent`。
- 若部分字段缺失：逐项继承 agent 配置，包括 `api_mode`、`reasoning_*`、`thinking_*`、`responses_tool_choice_compat`、`responses_force_stateless_replay` 与 `request_params`。
- `thinking_param_enabled` 默认继承 agent，也可在 historian 节或 `HISTORIAN_MODEL_THINKING_PARAM_ENABLED` 中独立覆盖。
- `use_proxy` 不继承 agent；`[models.historian]` 存在时未显式配置仍默认 `false`。
- `queue_interval_seconds=0` 时立即发车，`<0` 时回退到 agent 的间隔。

#### `[models.summary]` 消息总结模型

- 用于 `/summary`、`/sum` 与内部 SummaryService；主 AI 对话中的 `summary_agent` 仍走 `[models.agent]`。
- 若整个节缺失或为空：完整回退到 `models.agent`。
- 若部分字段缺失：逐项继承 agent 配置，包括 `api_mode`、`reasoning_*`、`thinking_*`、`responses_tool_choice_compat`、`responses_force_stateless_replay` 与 `request_params`。
- `thinking_param_enabled` 默认继承 agent，也可在 summary 节或 `SUMMARY_MODEL_THINKING_PARAM_ENABLED` 中独立覆盖。
- `use_proxy` 不继承 agent；`[models.summary]` 存在时未显式配置仍默认 `false`。

### 4.4.8 `[models.grok]` Grok 搜索模型

用途：
- 仅供 `web_agent` 内的 `grok_search` 子工具使用。
- 工具调用该模型时会注入专用 system prompt：以服务端当前时间作为“今天 / 最新 / 最近”的基准，要求先搜索、使用多组搜索查询或多个搜索工具、禁止编造，并在结果中给出来源。

默认：
- `max_tokens=8192`
- `queue_interval_seconds=1.0`（`0` 表示立即发车，`<0` 回退 `1.0`）
- `api_mode="openai.chat_completions"`
- `reasoning_enabled=false`
- `reasoning_effort="medium"`
- `thinking_param_enabled=true`
- `thinking_enabled=false`
- `thinking_budget_tokens=20000`
- `thinking_include_budget=true`
- `thinking_tool_call_compat=true`
- `reasoning_content_replay=true`
- `responses_tool_choice_compat=false`
- `responses_force_stateless_replay=false`
- `use_proxy=false`

补充：
- Grok 与其他生成模型一样支持三种 `api_mode` 及完整 thinking/reasoning/replay 配置。
- `[models.grok.request_params]` 的保留字段规则由所选 `api_mode` 决定。

### 4.4.9 模型池

相关节：
- `[models.chat.pool]`
- `[models.agent.pool]`
- `[[models.chat.pool.models]]`
- `[[models.agent.pool.models]]`

字段：

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `enabled` | `false` | 当前池开关 |
| `strategy` | `"default"` | `default` / `round_robin` / `random` |
| `models` | `[]` | 池中模型列表 |

`models` 条目支持字段：
- `model_name`（必填）
- `api_url` / `api_key` / `max_tokens` / `queue_interval_seconds`
- `api_mode` / `reasoning_enabled` / `reasoning_effort` / `reasoning_content_replay`
- `thinking_*`（包含 `thinking_param_enabled`）/ `system_prompt_as_user` / `responses_tool_choice_compat` / `responses_force_stateless_replay`
- `prompt_cache_enabled` / `stream_enabled` / `request_params`
- 以上可选字段缺省继承主模型
- `use_proxy` 是每个池条目独立开关，默认 `false`，不继承主模型，也没有池级总开关
- `queue_interval_seconds=0` 表示立即发车；`<0` 时回退到主模型间隔。

`request_params` 继承规则：
- `[[models.chat.pool.models]]` 与 `[[models.agent.pool.models]]` 的 `request_params` 会与主模型按顶层键浅合并。
- 同名键由池条目覆盖；嵌套对象按整键替换，不做深合并。

生效条件（全部满足才启用池）：
1. `features.pool_enabled=true`
2. 对应池 `enabled=true`
3. 池列表非空

### 4.4.10 `[models.embedding]` 嵌入模型

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `api_url` | `""` | 嵌入 API 地址 |
| `api_key` | `""` | API Key |
| `model_name` | `""` | 模型名 |
| `use_proxy` | `false` | 是否使用 `[proxy]` 中的代理地址 |
| `queue_interval_seconds` | `0.0` | 发车间隔（`0` 立即发车，`<0` 回退 `0.0`） |
| `dimensions` | `0` | 向量维度；`0`/空视为 `None`（模型默认） |
| `query_instruction` | `""` | 查询前缀 |
| `document_instruction` | `""` | 文档前缀 |
| `request_params` | `{}` | 额外请求体参数；保留字段如 `model`/`input`/`dimensions` 会忽略 |

### 4.4.11 `[models.rerank]` 重排模型

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `api_url` | `""` | rerank API 地址 |
| `api_key` | `""` | API Key |
| `model_name` | `""` | 模型名 |
| `use_proxy` | `false` | 是否使用 `[proxy]` 中的代理地址 |
| `queue_interval_seconds` | `0.0` | `0` 立即发车，`<0` 回退 `0.0` |
| `query_instruction` | `""` | 查询前缀 |
| `request_params` | `{}` | 额外请求体参数；保留字段如 `model`/`query`/`documents`/`top_n` 会忽略 |

### 4.4.12 `[models.image_gen]` / `[models.image_edit]` 生图模型

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `api_url` | `""` | OpenAI-compatible 生图 API 地址 |
| `api_key` | `""` | API Key |
| `model_name` | `""` | 模型名 |
| `use_proxy` | `false` | 是否让该模型请求使用 `[proxy]` 中的代理地址 |
| `context_window_tokens` | `0` | 预留字段；`0` 表示不参与文本上下文预算 |
| `request_params` | `{}` | 额外请求体参数 |

说明：
- `[models.image_gen].use_proxy` 控制 OpenAI-compatible 生图请求。
- `[models.image_edit].use_proxy` 控制参考图生图请求。
- `[image_gen].use_proxy` 控制非模型 provider（如星之阁）及图片下载链路，三者互不继承。
- 生图响应按 payload **自动识别** `http(s) url` / data URL / `url` 内原始 base64 / `b64_json` / `base64`，不依赖 `request_params.response_format` 或工具参数；后者只影响**请求**偏好。解码 base64 时会校验字母表与常见图片魔数，避免把错误文本当图片。

`request_params` 说明：
- 仅用于**请求体**字段，不包含 `api_key`、`base_url`、`timeout`、`extra_headers` 等 client 选项。
- 以下各模式列出的**运行时保留字段**由正式参数或专用配置派生；`request_params` 中的同名值会被忽略，不能覆盖最终请求体。未列出的字段才会透传，另行说明的合并字段除外。
- `openai.chat_completions` 运行时保留字段：`model`、`messages`、`max_tokens`、`tools`、`tool_choice`、`stream`、`stream_options`、`thinking`、`reasoning_effort`、`output_config`。`request_params.reasoning` 是兼容网关的透传例外；专用 `max_tokens` 仅在值为正数时发送，非正数时省略。
- `openai.responses` 运行时保留字段：`model`、`input`、`instructions`、`max_output_tokens`、`tools`、`tool_choice`、`previous_response_id`、`stream`、`stream_options`、`thinking`、`reasoning_effort`、`output_config`。`request_params.reasoning` 是合并例外，其 `summary` 等附加键会保留，专用 effort 会覆盖同名 `effort`；专用 `max_tokens` 仅在值为正数时映射为 `max_output_tokens`，非正数时省略。历史 `output` items 由运行时维护，不要手工覆盖 `function_call.id` / `call_id`。
- `anthropic.messages` 运行时保留字段：`model`、`messages`、`system`、`max_tokens`、`tools`、`tool_choice`、`stream`、`thinking`、`reasoning`、`reasoning_effort`、`prompt_cache_key`。`request_params.output_config` 是合并例外，其中其他键会保留，专用 effort 会覆盖同名 `effort`；`max_tokens` 必须为正整数并原样发送。
- 启用 `stream_enabled` 且使用 `openai.chat_completions` 时，运行时自动发送 `stream_options.include_usage=true`；Responses 与 Anthropic 分别使用各自 SDK 的流式接口并聚合最终响应。
- 流式请求仅在明确的流式参数不兼容错误或 SDK 未实现时回退到非流式请求；鉴权、限流、网络、超时、解析或代码异常会直接暴露，便于定位真实问题。
- embedding 保留字段：`model`、`input`、`dimensions`。
- rerank 保留字段：`model`、`query`、`documents`、`top_n`、`return_documents`。

---

### 4.5 `[knowledge]` 本地知识库

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `enabled` | `false` | 是否启用知识库 | 启用后需 embedding 配置完整 |
| `base_dir` | `"knowledge"` | 知识库根目录 | |
| `auto_scan` | `false` | 是否定时扫描文件变化 | |
| `auto_embed` | `false` | 是否自动执行嵌入 | |
| `scan_interval` | `60.0` | 扫描间隔（秒） | `<=0` 回退 `60.0` |
| `embed_batch_size` | `64` | 批大小 | `<=0` 回退 `64` |
| `chunk_size` | `10` | 分块窗口大小（按行） | `<=0` 回退 `10` |
| `chunk_overlap` | `2` | 相邻块重叠行数 | `<0` 回退 `0` |
| `default_top_k` | `5` | 召回数量 | `<=0` 回退 `5` |
| `enable_rerank` | `false` | 是否启用二阶段重排 | 自动约束见下 |
| `rerank_top_k` | `3` | 重排后返回数量 | `<=0` 回退 `3` |

重排约束：
- `rerank_top_k` 必须 `< default_top_k`。
- 若不满足，自动回退为 `default_top_k - 1`。
- 若 `default_top_k <= 1`，则自动禁用 rerank。

自动扫描行为：
- `auto_scan=true` 且 `auto_embed=true`：持续周期扫描。
- `auto_scan=false` 且 `auto_embed=true`：仅启动时做一次初始扫描。
- `auto_embed=false`：仅手动触发。

---

### 4.6 `[logging]` 日志

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `level` | `"INFO"` | 日志级别（DEBUG/INFO/WARNING/ERROR） |
| `file_path` | `"logs/bot.log"` | 日志文件路径 |
| `max_size_mb` | `10` | 单文件轮转大小（MB） |
| `backup_count` | `5` | 轮转保留数量 |
| `tty_enabled` | `false` | 是否输出到终端 |
| `log_thinking` | `true` | 是否记录思维链日志 |

说明：
- `max_size_mb` 运行时会转成字节。
- `logging.level/file_path/max_size_mb/backup_count/tty_enabled` 变更需重启。
- `log_thinking` 可热更新（请求时动态读取）。

---

### 4.7 `[tools]` Tool Schema 兼容配置

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `dot_delimiter` | `"-_-"` | 将工具名中的 `.` 映射为分隔符 | 仅允许 `[a-zA-Z0-9_-]` 且不能含 `.`，非法回退默认 |
| `description_truncate_enabled` | `false` | 是否按长度截断工具描述 | |
| `description_max_len` | `1024` | 工具描述最大长度 | `<=0` 时内部使用默认 1024 |
| `sanitize_verbose` | `false` | 输出工具清洗明细日志 | |
| `description_preview_len` | `160` | 日志预览长度 | `<=0` 时内部使用默认 160 |

补充：描述清洗（控制字符、空白规整等）始终开启；`description_truncate_enabled` 仅控制“长度截断”。

---

### 4.8 `[features]` 功能总开关

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `nagaagent_mode_enabled` | `false` | NagaAgent 能力进程总闸；实际是否启用还受 `[naga].mode` 会话策略约束 |
| `pool_enabled` | `false` | 多模型池全局总开关 |

---

### 4.9 `[easter_egg]` 彩蛋行为

| 字段 | 默认值 | 说明 | 取值 |
|---|---:|---|---|
| `agent_call_message_enabled` | `"none"` | 调用提示模式 | `none` / `agent` / `tools` / `all` / `clean` |
| `keyword_reply_enabled` | `false` | 群聊关键词自动回复 | 布尔 |
| `repeat_enabled` | `false` | 群聊复读（连续 N 条相同消息时复读） | 布尔 |
| `repeat_threshold` | `3` | 触发复读所需的连续相同消息条数（来自不同发送者） | 整数，2–20 |
| `repeat_cooldown_minutes` | `60` | 复读冷却时间（分钟）。同一内容被复读后，在冷却期内不再重复复读。？和 ? 视为等价。0 = 无冷却 | 整数，≥ 0 |
| `inverted_question_enabled` | `false` | 倒问号（复读触发时若消息为问号则发送 ¿） | 布尔 |

复读支持图片等已登记附件：当连续相同内容是 `<attachment uid="..."/>` 图片引用时，系统会先渲染成真实图片消息再发送，不会把 UID 占位字符串直接发到群里。

兼容：历史字段 `[core].keyword_reply_enabled` 仍可读取，建议迁移到 `[easter_egg]`。

---

### 4.10 `[history]` 历史消息

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `max_records` | `10000` | 每个会话最多保留条数 |
| `summary_fetch_limit` | `1000` | `/summary` 按条数拉取时的最大消息条数（可配置，无固定 500 硬编码；受 `max_records` 约束） |
| `summary_time_fetch_limit` | `5000` | `/summary` 按时间范围查询时的最大扫描条数（可配置） |

说明：该值主要在 `MessageHistoryManager` 初始化时使用，运行中修改建议重启后再观察效果。消息进入后会先同步写入内存历史，供命令、自动管线与 AI 后续流程立即读取；磁盘 JSON 持久化按会话在后台串行合并写入，连续消息会合并为最新快照，降低复读等快路径被大历史文件全量落盘阻塞的概率。`/summary` 命令本身不再将条数钳制到 500，实际上限由 `summary_fetch_limit` 与 `max_records` 决定。

### 4.10.1 `[attachments]` 附件缓存

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `remote_download_max_size_mb` | `25` | 远程附件自动下载并缓存的最大大小（MB）。超过上限时只登记 URL 引用；设为 `0` 可完全禁用远程附件下载 |
| `use_proxy` | `false` | 远程附件下载是否使用 `[proxy]` 中的代理地址 |
| `cache_max_total_size_mb` | `0` | 附件缓存文件总大小上限（MB）。`0` 表示不按总容量清理；达到上限时优先删除最旧本地缓存副本，有 URL 的记录会保留 UID 与 URL 以便后续回源 |
| `cache_max_records` | `2000` | 附件登记记录最大数量。`0` 表示不限制数量 |
| `cache_max_age_days` | `7` | 附件本地缓存最长保留天数。`0` 表示不按时间清理；有 URL 的记录只删除本地副本并保留 UID/URL，无 URL 的老记录会被删除 |
| `url_reference_max_records` | `2000` | 仅 URL 引用的附件记录最大数量。`0` 表示不限制 |
| `url_max_length` | `8192` | 允许登记的远程附件 URL 最大长度。`0` 表示不限制长度 |

外部接收的远程图片或文件默认会先下载到附件缓存再生成 UID，避免后续 URL 失效；大文件超过阈值时，UID 仍会生成，但绑定的是 URL 引用而不是缓存文件，AI 可在上下文中看到原始 `source_ref`。如果本地缓存因总容量或时间清理被删除，但记录仍保留 URL，后续需要文件内容时会优先按 URL 回源下载。

合并转发会复用同一注册表登记为 `forward_...` UID，并在实时 AI 输入中显示为 `<forward uid="..."/>`。收到合并转发时会在预处理阶段递归保存当前可访问的转发树到 `data/cache/forward_snapshots/`，后续 `messages.get_forward_msg` 读取时优先使用本地快照；缺失时才回源 OneBot 并补写快照。历史记录仍保留递归展开后的文本，但同一轮 prompt 会按 `message_id` 剔除当前消息的历史副本，因此实时上下文只保留 UID；需要查看第一层或内层内容时，AI 会调用工具按层读取，内层合并转发会继续分配新的 `forward_...` UID。如果协议端无法二次读取内层转发，会返回明确诊断和可见原始字段。

### 4.10.2 `[message_batcher]` 同 sender 短时消息合并

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `enabled` | `true` | 总开关，默认开启；关闭后行为退化为旧版的逐条独立 AI 调用。当前主提示词按 batcher 开启后的"当前输入批次"语义适配，若关闭可能导致连续补充/修正消息与提示词语义不匹配，需要单独调整提示词或接受旧版逐条触发行为 |
| `window_seconds` | `5.0` | 同 sender 合并的等待窗口（秒） |
| `strategy` | `"extend"` | `extend` = 新消息重置窗口；`fixed` = 从首条算起的固定窗口 |
| `max_window_seconds` | `30.0` | 从首条算起最长等待，硬顶 `extend` 不被无限延长；`0` 表示不限制（仅靠 `window_seconds` + `max_messages_per_batch` 触发发车） |
| `max_messages_per_batch` | `0` | 单批最多条数；达到立即发车，`0` = 不限 |
| `group_enabled` | `true` | 群聊是否启用合并 |
| `private_enabled` | `true` | 私聊是否启用合并 |
| `flush_on_command` | `false` | 命中斜杠命令时是否先 flush 该 sender 的 buffer；默认关闭以保持命令独立执行 |
| `pre_send_seconds` | `0.0` | 投机预发送阈值（秒）。`0 < pre_send_seconds < window_seconds` 时启用：静默到该阈值先把当前 batch 提前发给 LLM 抢时间（speculative pre-fire），但 batch 仍要等到 `window_seconds` 才正式结束；新消息在投机期间到达且 inflight 调用尚未发出消息时会取消 inflight 并把消息合并入下一轮调用。`0` 或 `>= window_seconds` 视为关闭 |
| `allow_cancel_after_send` | `false` | 投机调用已向用户发出消息后是否仍允许新消息取消该 inflight。默认 `false`（安全：不取消，新消息开新 batch）；启用后可能造成重复发送 |

启用后，同一发送者在窗口内连续发送的多条消息会合并到同一轮 AI 调用，`<message>` 块按时间顺序排列，并带有"当前输入批次"说明，AI 一次性处理整批意图。拍一拍永远旁路立即处理；群聊已有 buffer 时新到的 @bot 也会单独立即处理（不打断 buffer）；首条 @bot 进入 buffer 时整批发车走 `add_group_mention_request`。配置支持热更新，关停时会 `flush_all` 并等待队列 drain，避免缓冲消息只入队未执行。详细行为矩阵与设计要点见 [docs/message-batching.md](message-batching.md)。

---

### 4.11 `[skills]` 技能系统与 Agent 介绍

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `hot_reload` | `true` | 是否启用技能热重载 |
| `hot_reload_interval` | `2.0` | 扫描间隔（秒） |
| `hot_reload_debounce` | `0.5` | 去抖时间（秒） |
| `intro_autogen_enabled` | `true` | 是否自动生成 agent intro |
| `intro_autogen_queue_interval` | `1.0` | intro 生成队列发车间隔（`0` 立即发车，`<0` 回退 `1.0`） |
| `intro_autogen_max_tokens` | `8192` | intro 生成上限 |
| `intro_hash_path` | `.cache/agent_intro_hashes.json` | intro hash 缓存 |
| `prefetch_tools` | `["get_current_time"]` | 预先执行并注入 system 的工具列表 |
| `prefetch_tools_hide` | `true` | 预取成功后是否从 tool list 隐藏该工具；失败时仍保留 schema |
| `tool_search_enabled` | `false` | 是否为主 AI 启用按需工具搜索；关闭时保持全量工具声明行为 |
| `tool_search_always_loaded` | `["send_message", "end"]` | Tool Search 启用后始终向主 AI 暴露的工具名列表 |
| `tool_search_max_results` | `5` | 单次工具搜索最多加载的匹配数量；小于 `1` 时按 `1` 处理 |

补充：
- `prefetch_tools` 未配置时默认会注入 `get_current_time`。
- `hot_reload_interval/debounce` 还会用于配置热更新监听器本身。
- `tool_search_*` 支持热更新，只影响热更新后的新 `ask()`；正在运行的请求继续使用创建时的工具快照。
- Tool Search 的查询语法、逐轮加载流程和兼容边界见 [Tool Search 按需工具加载](tool-search.md)。

---

### 4.11.1 `[prompt.system_info]` Prompt 系统信息注入

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `enabled` | `false` | 总开关。开启后把当前运行主机的系统信息注入主模型 Prompt；默认关闭，避免升级后自动暴露本机信息给上游模型 |
| `show_os` | `true` | 展示操作系统、版本、release 与架构 |
| `show_runtime` | `true` | 展示 Python 与 Undefined 版本 |
| `show_host` | `true` | 展示主机名 |
| `show_cpu` | `true` | 展示 CPU 型号、物理核心数与逻辑核心数 |
| `show_cpu_usage` | `true` | 展示当前 CPU 总使用率 |
| `show_memory` | `true` | 展示内存总量、已用量与占用率 |
| `show_swap` | `true` | 展示 Swap 总量、已用量与占用率 |
| `show_disks` | `true` | 展示可见磁盘分区、文件系统、容量与占用率 |
| `show_network` | `true` | 展示非回环网卡地址与网络收发累计；涉及 IP 信息，公网或共享部署可关闭 |
| `show_process` | `true` | 展示 Bot 进程 PID、启动时间、运行时长、RSS 与进程 CPU 占用 |
| `show_uptime` | `true` | 展示系统启动时间与系统运行时长 |

采集实现优先使用 `psutil` 与 Python 标准库 `platform/socket/os/time`，目标是 Windows、macOS、Linux 跨平台可用。单项采集失败时只省略该项，不会中断 Prompt 构建。该块属于动态上下文，会放在历史/记忆之后、`【当前时间】` 之前。

安全边界：不会注入 API Key、环境变量、命令行参数、完整配置文件内容、用户目录文件列表等敏感内容。主机名、网络地址、磁盘挂载点和 PID 属于运维信息，启用前请确认当前模型供应商和部署场景允许暴露这些信息。

---

### 4.12 `[search]` 搜索

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `priority` | `["grok_search", "firecrawl_search", "web_search"]` | `web_agent` 搜索工具优先级；关闭的工具会隐藏，开启后仅通过提示词引导选择 |
| `searxng_url` | `""` | SearXNG 地址；为空则禁用搜索包装器 |
| `grok_search_enabled` | `false` | 是否在 `web_agent` 中暴露 `grok_search`；关闭时隐藏该工具 |
| `firecrawl_search_enabled` | `false` | 是否在 `web_agent` 中暴露 `firecrawl_search`；关闭时隐藏该工具 |
| `use_proxy` | `false` | 搜索相关 HTTP 请求是否使用 `[proxy]` 中的代理地址 |

#### `search.firecrawl`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `api_key` | `""` | Firecrawl API Key；为空时使用 keyless 搜索 |
| `base_url` | `"https://api.firecrawl.dev"` | Firecrawl API 基础地址 |

补充：
- `searxng_url` 可热更新，运行时会重建搜索客户端。
- `grok_search_enabled`、`firecrawl_search_enabled`、`search.firecrawl.*`、`priority` 不需要重建客户端；它们影响 `web_agent` 的工具暴露和提示词优先级。
- `firecrawl_search` 调用 Firecrawl `POST /v2/search`；配置 `api_key` 时发送 `Authorization: Bearer`，为空则走 Firecrawl keyless。

---

### 4.13 `[proxy]` 代理

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `http_proxy` | `""` | HTTP 代理地址 |
| `https_proxy` | `""` | HTTPS 代理地址 |

环境变量兜底：
- 若 TOML 未配置 `http_proxy` / `https_proxy`，会尝试 `HTTP_PROXY` / `HTTPS_PROXY`。

说明：
- `[proxy]` 只保存代理地址，不再包含全局启用开关。
- 是否使用代理由各功能段或模型段的 `use_proxy` 独立控制，默认均为 `false`。
- 本机 Runtime API、WebUI、Tauri 本机/内网桥接不走这里的公网代理配置。

---

### 4.14 `[network]` 网络请求默认参数

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `request_timeout_seconds` | `30.0` | 默认请求超时（秒） | `<=0` 回退 `480.0` |
| `request_retries` | `0` | 默认重试次数 | 自动钳制到 `0..5` |

---

### 4.15 `[render]` HTML/Markdown 图片渲染

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `browser_max_concurrency` | `0` | 渲染浏览器最大同时开启数量 | `<=0` 时启用自动值：Linux=`1`，其它平台=`2` |
| `browser_executable_path` | `""` | 可选 Chrome/Chromium 可执行文件路径 | 留空时优先使用 Playwright 自带浏览器；其缺失时自动查找系统 Chrome/Chromium |
| `use_proxy` | `false` | 网页抓取链路是否使用 `[proxy]` 中的代理地址 | HTML/Markdown 浏览器渲染始终离线，不使用代理 |
| `long_image_default_width` | `900` | `layout=long` 未传 `width` 时的最终图片宽度（像素） | 自动钳制到 `320..2048` |
| `long_image_default_padding` | `28` | `layout=long` 未传 `padding` 时的内边距（像素） | 自动钳制到 `0..160`，且保证小于宽度的一半 |

说明：
- 浏览器路径、并发和长图配置只影响 `render.py` 的 HTML/Markdown 图片渲染链路；`use_proxy` 仍供 `crawl_webpage` 等独立网页抓取实现使用。
- 渲染浏览器当前采用单例复用，因此这里限制的是并发页面/上下文数量，而不是浏览器进程数量。
- 显式修改 `browser_executable_path` 后需重启 Bot；仅当 Playwright 报告自带浏览器缺失时才会自动回退到系统浏览器，其他启动错误仍会原样报出。
- 配置变更会对后续新的渲染请求生效；已在执行中的渲染任务不受影响。
- `render.render_html` 和 `render.render_markdown` 默认使用 `layout=default`，视觉效果与旧版一致。显式传 `layout=long` 时，高度按内容自动延伸，使用 CSS 像素截图保证 `width` 对应最终图片宽度，并去掉两侧外部留白。
- `width` 可选范围为 `320..2048`，`padding` 可选范围为 `0..160`；两者只能与 `layout=long` 一起使用。HTML 长图支持内联 CSS、脚本和 `data:` / `blob:` 资源；BrowserContext 强制离线并终止全部网络请求，外部图片、字体、样式和脚本不会加载。`padding=0` 可用于全幅设计。

#### `[render.cache]` HTML 渲染结果缓存

基于 HTML 内容 hash 复用同一张图片，避免重复渲染（help、profile、render_markdown 等链路自动受益）。

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `enabled` | `true` | 是否启用渲染缓存 | 关闭时所有请求都会走 playwright 重新截图 |
| `max_entries` | `50` | LRU 条目数上限 | 自动钳制到 `>=1`；超过时按 `last_accessed_at` 淘汰 |
| `max_size_mb` | `50` | 缓存总占用上限（MB） | 自动钳制到 `>=1`；超过时按 LRU 顺序持续淘汰 |
| `flush_interval_seconds` | `2.0` | 元数据落盘最小间隔（秒） | 自动钳制到 `>=0`；关停时强制刷盘 |

说明：
- 元数据通过 `utils/io.py` 的 `read_json` / `write_json` 写入，自带文件锁与原子替换。
- 缓存图片落在 `data/cache/render/html/` 目录，元数据为同目录下 `_html_render_cache.json`。
- 进程关停（含 Ctrl+C）时会调用 `close_render_cache` 强制刷盘，保证最近访问时间不丢失。
- 配置改动后下次启动生效。运行期热更新仅影响新建的缓存实例，已加载的单例沿用启动时参数。

---

### 4.16 `[api_endpoints]` 第三方 API 基址

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `xxapi_base_url` | `https://v2.xxapi.cn` | XXAPI 基址 |
| `xingzhige_base_url` | `https://api.xingzhige.com` | 星之阁基址 |

说明：以上值会自动去除末尾 `/`。

### 4.16.1 `[image_gen]` 生图工具

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `provider` | `"xingzhige"` | 生图 provider：`xingzhige` 或 `models` |
| `use_proxy` | `false` | 非模型 provider 请求与生成图片下载是否使用 `[proxy]` 中的代理地址 |
| `xingzhige_size` | `"1:1"` | 星之阁模式下的默认图片比例 |
| `openai_size` | `""` | OpenAI-compatible 生图尺寸；空字符串表示不传 |
| `openai_quality` | `""` | OpenAI-compatible 生图质量；空字符串表示不传 |
| `openai_style` | `""` | OpenAI-compatible 生图风格；空字符串表示不传 |
| `openai_timeout` | `120.0` | OpenAI-compatible 生图请求超时（秒） |

说明：`provider="models"` 时，模型请求是否走代理由 `[models.image_gen].use_proxy` / `[models.image_edit].use_proxy` 控制；`[image_gen].use_proxy` 只控制工具自身的非模型 HTTP 请求。

---

### 4.17 `[xxapi]` 与 `[weather]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `xxapi.api_token` | `""` | XXAPI token（前往 https://xxapi.cn 获取）|

说明：`weather.api_key` 当前主要作为兼容保留项。

---

### 4.18 `[token_usage]` Token 归档

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `max_size_mb` | `5` | 主文件超过该大小后归档，`<=0` 禁用 |
| `max_archives` | `30` | 最大归档数量，`<=0` 不限制 |
| `max_total_mb` | `0` | 归档总大小上限，`<=0` 禁用 |
| `archive_prune_mode` | `"delete"` | 清理模式：`delete` / `merge` / `none` |

模式别名：
- `delete` 兼容 `prune/drop`
- `merge` 兼容 `repack/lossless`
- `none` 兼容 `keep/off/disable`

---

### 4.19 `[mcp]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `config_path` | `config/mcp.json` | MCP 配置文件路径 |

可配合 `config/mcp.json.example` 使用。

---

### 4.20 `[messages]` 消息工具限制

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `use_proxy` | `false` | URL 文件下载等消息工具联网请求是否使用 `[proxy]` 中的代理地址 | |
| `send_text_file_max_size_kb` | `512` | 文本文件发送上限（KB） | `<=0` 回退 `512` |
| `send_url_file_max_size_mb` | `100` | URL 文件发送上限（MB） | `<=0` 回退 `100` |

---

### 4.20.1 `[lxmusic2api]` 音乐服务

`music.*` 工具由独立部署的 [lxmusic2api](https://github.com/69gg/lxmusic2api) 提供数据与音频解析能力。请先按照上游仓库说明完成部署、配置唯一自定义音源并确认其许可证及使用限制，再填写：

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `base_url` | `http://127.0.0.1:3000` | lxmusic2api 服务根地址 | 推荐不带 `/v1`；末尾 `/` 自动移除；仅接受 HTTP(S) 地址 |
| `api_key` | `""` | 与 lxmusic2api `[auth].api_key` 一致的 Bearer Key | 留空时全部 `music.*` 工具从模型工具列表隐藏 |

```toml
[lxmusic2api]
base_url = "http://127.0.0.1:3000"
api_key = "replace-with-your-key"
```

配置会随 `config.toml` 热更新：修改 `base_url` 或 `api_key` 后，后续工具调用与工具可见性立即使用新值，无需重启。音乐工具沿用全局 `[access]` 会话访问控制，不另设用户白名单。

音频附件模式受 `[attachments].remote_download_max_size_mb` 限制；值为 `0` 时应改用 `music.get_audio(delivery="url")`。URL 是上游自定义音源产生的短时直链，可能快速失效。上游受管下载文件采用最长 24 小时保留并自动清理；本集成不暴露下载任务生命周期接口，流式音频注册后的本地附件仍按 Undefined 的 `[attachments]` 缓存策略清理。部署者应根据版权、许可证与当地法律调整缓存保留并只处理有权使用的内容。

---

### 4.21 `[bilibili]` 自动提取

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `use_proxy` | `false` | Bilibili API、短链解析、视频/弹幕请求是否使用 `[proxy]` 中的代理地址 | |
| `auto_extract_enabled` | `false` | 是否自动提取 B 站链接/BV | |
| `cookie` | `""` | 完整 Cookie 字符串 | 支持兼容旧字段 `sessdata`（不推荐） |
| `prefer_quality` | `80` | 目标清晰度（80/64/32） | |
| `max_duration` | `600` | 最大时长（秒），`0` 不限 | |
| `max_file_size` | `100` | 最大体积（MB），`0` 不限 | |
| `oversize_strategy` | `"downgrade"` | 超限策略 | 仅 `downgrade/info`，非法回退 `downgrade` |
| `danmaku_enabled` | `true` | 是否在自动提取合并转发中附带弹幕 | |
| `danmaku_batch_size` | `100` | 每个内层弹幕合并转发包含的弹幕条数 | `<=0` 回退 `100` |
| `danmaku_max_count` | `0` | 最多提取多少条弹幕，`0` 不限 | `<0` 回退 `0` |
| `auto_extract_group_ids` | `[]` | 功能级群白名单 | 空时跟随全局 access |
| `auto_extract_private_ids` | `[]` | 功能级私聊白名单 | 空时跟随全局 access |

自动提取行为：
- 命中 B 站链接、BV 号或 AV 号后，自动提取会发送一次外层合并转发，固定包含三个节点：视频信息、视频文件或视频状态、弹幕列表。
- 弹幕通过 Bilibili protobuf 接口分段拉取；项目内置了解码逻辑，无需安装 `protoc` 或额外生成 protobuf 代码。
- 弹幕列表节点会按每 100 条弹幕生成一个内层合并转发；每条弹幕对应内层合并转发中的一个节点，便于在客户端逐条查看。
- 视频文件下载、清晰度、时长和体积限制仍由本节配置控制；自动提取的转发消息会通过统一发送层写入历史。后续实时 AI 上下文遇到合并转发时只看到 `forward_...` UID，需要内容时按层调用 `messages.get_forward_msg` 读取。

---

### 4.21.1 `[douyin]` 自动提取

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `use_proxy` | `false` | 抖音短链解析、share 页、ttid 注册和视频流请求是否使用 `[proxy]` 中的代理地址 | |
| `auto_extract_enabled` | `false` | 是否自动提取抖音短链、长链或 aweme_id | |
| `max_duration` | `600` | 最大时长（秒），`0` 不限 | `<0` 回退 `600` |
| `max_file_size` | `100` | 最大体积（MB），`0` 不限 | `<0` 回退 `100` |
| `prefer_ratios` | `["1080p","720p","540p","360p"]` | 清晰度探测顺序 | 非法或空列表回退默认顺序 |
| `auto_extract_group_ids` | `[]` | 功能级群白名单 | 空时跟随全局 access |
| `auto_extract_private_ids` | `[]` | 功能级私聊白名单 | 空时跟随全局 access |
| `auto_extract_max_items` | `3` | 单条消息最多自动处理几个视频 | `<=0` 回退 `3`，`>10` 截断到 `10` |

自动提取行为：
- 命中 `v.douyin.com/...`、`douyin.com/video/<id>` 或裸 aweme_id 后，自动提取会发送一次两节点合并转发：视频信息、视频文件或视频状态。
- 下载链路走抖音 SSR share 页中的 `window._ROUTER_DATA`，从 `video.play_addr` 提取 token，再按 `prefer_ratios` 探测 `aweme/v1/play/`。
- play 端点探测使用 2 字节 Range GET，并优先按 `Content-Range` 中的总长度对重复文件去重，缺失时回退 `Content-Length`；游客 share 页没有 `bit_rate` 时仍可选择实际可下载档位。
- 若超过时长或体积限制，会跳过下载并只发送视频信息与状态节点。需要分析视频内容时，`file_analysis_agent` 可通过 `douyin_video(output_mode=uid)` 获取视频附件 UID 后再分析；只需标题、作者、时长和简介等元信息时可使用 `douyin_video(output_mode=info)`。

---

### 4.20.1 `[arxiv]` 自动提取

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `use_proxy` | `false` | arXiv API 与 PDF 下载是否使用 `[proxy]` 中的代理地址 | |
| `auto_extract_enabled` | `false` | 是否自动提取 arXiv 论文 | |
| `max_file_size` | `100` | 最大 PDF 体积（MB），`0` 不限 | `<0` 回退 `100` |
| `auto_extract_group_ids` | `[]` | 功能级群白名单 | 空时跟随全局 access |
| `auto_extract_private_ids` | `[]` | 功能级私聊白名单 | 空时跟随全局 access |
| `auto_extract_max_items` | `5` | 单条消息最多自动处理几篇论文 | `<=0` 回退 `5`，`>20` 截断到 `20` |
| `author_preview_limit` | `20` | 信息消息中作者预览上限 | `<=0` 回退 `20`，`>100` 截断到 `100` |
| `summary_preview_chars` | `1000` | 信息消息中摘要预览字符数上限 | `<=0` 回退 `1000`，`>8000` 截断到 `8000` |

触发规则：
- 命中 `arxiv.org/abs/...`、`arxiv.org/pdf/...` 或 `arXiv:<id>` 时直接触发。
- 裸新式编号仅在消息中同时出现 `arxiv` 关键词时触发，避免误判普通数字串。
- PDF 下载或上传失败时不会额外发送失败提示，只保留论文信息消息。
- 自动提取仍默认发送论文信息与 PDF；若用户要求分析 arXiv 论文内容，`file_analysis_agent` 会通过 `arxiv_paper(output_mode=uid)` 获取 PDF 附件 UID 后再分析；只需标题、作者、摘要和链接等元信息时可使用 `arxiv_paper(output_mode=info)`。

---

### 4.20.2 `[github]` 仓库自动提取

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `use_proxy` | `false` | GitHub API 请求和仓库卡片渲染资源加载是否使用 `[proxy]` 中的代理地址 | |
| `auto_extract_enabled` | `false` | 是否自动提取 GitHub 仓库链接或 `owner/repo` 仓库 ID | |
| `request_timeout_seconds` | `10.0` | GitHub API 请求超时（秒），作为显式超时传入，不被 `[network].request_timeout_seconds` 覆盖 | `<=0` 回退 `10`，`>60` 截断到 `60` |
| `request_retries` | `2` | GitHub API 请求重试次数，仅重试网络/超时异常和 `429`/`5xx` 状态码 | `<0` 回退 `0`，`>5` 截断到 `5` |
| `auto_extract_group_ids` | `[]` | 功能级群白名单 | 空时跟随全局 access |
| `auto_extract_private_ids` | `[]` | 功能级私聊白名单 | 空时跟随全局 access |
| `auto_extract_max_items` | `3` | 单条消息最多自动处理几个仓库 | `<=0` 回退 `3`，`>10` 截断到 `10` |

触发规则：
- 命中 `https://github.com/owner/repo`、`github.com/owner/repo` 或 `git@github.com:owner/repo.git` 时触发。
- 裸 `owner/repo` 会作为 GitHub 仓库 ID 尝试一次 public API 请求；失败时只记录日志，不向会话发送错误消息。
- 仅支持 public 仓库。卡片渲染为图片，包含仓库 ID、作者头像、简介、stars、forks、issues、contributors、watchers、语言、许可证、默认分支和更新时间等信息。
- GitHub API 请求默认不使用代理；需要时设置 `[github].use_proxy = true`，代理地址来自 `[proxy]`。
- 自动提取失败日志会记录异常类型、`repr(exc)` 和堆栈，便于定位代理连接失败等 `str(exc)` 为空的异常。

自动提取调度说明：
- 斜杠命令优先级高于自动处理管线；命中命令后直接分发并结束本轮后续处理，不会触发自动提取或 AI 自动回复。命令输入和命令输出会写入历史，供后续 AI 轮次读取。
- 同一条消息内，自动处理管线会并行检测 Bilibili、Douyin、arXiv、GitHub 等已注册管线。
- 检测到多个管线时会并行处理全部命中结果；通常单条消息只会命中一个管线，因此不手动维护优先级。
- 自动提取发送出的信息消息、图片卡片、文件或视频摘要会通过统一发送层写入消息历史，本地媒体和文件会自动登记为会话附件 UID，随后才进入 AI 自动回复，因此 AI 可以读取刚刚的自动提取结果。
- 管线实现位于 `src/Undefined/skills/pipelines/`，跟随 `[skills]` 热重载配置自动重新加载。开发新管线请参考 [自动处理管线开发指南](pipelines.md)。

---

### 4.22 `[code_delivery]` 代码交付 Agent

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `enabled` | `true` | 启用 Code Delivery Agent | |
| `task_root` | `data/code_delivery` | 任务根目录 | |
| `docker_image` | `ubuntu:24.04` | Docker 镜像 | |
| `container_name_prefix` | `code_delivery_` | 容器名前缀 | |
| `container_name_suffix` | `_runner` | 容器名后缀 | |
| `default_command_timeout_seconds` | `0` | 默认命令超时，`0` 为不限时 | 若该字段缺失，内部回退到 600 秒 |
| `max_command_output_chars` | `20000` | 命令输出截断阈值 | |
| `default_archive_format` | `zip` | 归档格式 | 仅 `zip/tar.gz`，非法回退 `zip` |
| `max_archive_size_mb` | `200` | 归档大小上限 | |
| `cleanup_on_finish` | `true` | 任务结束后清理容器和目录 | |
| `cleanup_on_start` | `true` | 启动时清理残留容器和目录 | |
| `llm_max_retries_per_request` | `5` | LLM 连续失败阈值（预留） | |
| `notify_on_llm_failure` | `true` | 连续失败是否通知（预留） | |
| `container_memory_limit` | `""` | Docker `--memory` | 空表示不限 |
| `container_cpu_limit` | `""` | Docker `--cpus` | 空表示不限 |
| `command_blacklist` | 内置危险命令列表 | 命令黑名单（支持通配） | 运行时同时做 `fnmatch` 与子串匹配 |

---

### 4.23 `[webui]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `url` | `127.0.0.1` | WebUI 监听地址 |
| `port` | `8787` | WebUI 端口（1..65535） |
| `password` | `changeme` | WebUI 登录密码 |
| `autostart_bot` | `false` | WebUI 启动时是否自动启动机器人进程 |
| `check_updates` | `true` | 打开 WebUI 时是否在后台检查 GitHub 正式 Release |

关键行为：
- 默认密码 `changeme` 禁止登录，必须先修改。
- 未配置或为空时，会回退默认密码并标记为”默认密码模式”。
- `webui.url/port/password/autostart_bot` 修改需重启 WebUI 进程（机器人主进程中也属于重启生效类）。
- `check_updates` 支持热更新；关闭后只停止页面打开时的自动检查，概览页仍可手动检查。
- `autostart_bot=true` 时，运行 `uv run Undefined-webui` 会自动拉起 bot 进程，无需手动点击启动按钮；与 WebUI 更新重启后的自动恢复机制（`pending_bot_autostart` marker）互不冲突。
- 自动检查在 WebUI 鉴权成功后异步执行，失败不会阻塞或打扰页面。GitHub Release 查询在 WebUI 进程内缓存 15 分钟；同一时刻的并发检查会共享一个在途任务，查询失败时也不会逐个重试外部请求。
- 自动更新仅支持官方 `origin`、本地 `main` 和干净工作区；确认后会精确快进到最新正式 Release 标签，而不是拉取该标签之后尚未发版的 `main` 提交。

---

### 4.24 `[weixin]` 微信 ClawBot / iLink 私聊

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `enabled` | `false` | 微信 iLink 总开关；关闭时不建立网络连接 |
| `state_dir` | `data/weixin` | 敏感凭据、游标、绑定、隔离和审计状态目录 |
| `long_poll_timeout_seconds` | `35.0` | 单次消息长轮询超时 |
| `stale_token_pause_seconds` | `3600.0` | token 失效提示后的暂停时间 |
| `retry_delay_seconds` | `2.0` | 普通失败重试间隔 |
| `failure_backoff_seconds` | `30.0` | 连续失败后的退避时间 |
| `failures_before_backoff` | `3` | 进入长退避的连续失败阈值 |
| `media_max_size_mb` | `100` | 单个媒体大小上限 |
| `media_upload_attempts` | `3` | 媒体上传遇到临时网络或服务端错误时的最大尝试次数，范围 1..10 |
| `media_upload_concurrency` | `3` | 单条多项目消息并发上传媒体的上限，范围 1..8 |
| `multi_item_messages_enabled` | `true` | 优先用 iLink 多项目消息模拟微信合并转发 |
| `multi_item_max_items` | `10` | 单次多项目消息的项目上限，范围 1..20；超出时保持顺序分批 |
| `login_session_ttl_seconds` | `300.0` | 二维码登录会话有效期 |
| `privileged_confirmation_ttl_seconds` | `300.0` | 管理员身份二次确认有效期 |
| `pending_max_records` | `100` | 未知来源隔离记录上限 |
| `audit_max_records` | `1000` | 帐号管理审计记录上限 |

关键行为：
- 修改本节后需重启 Bot 主进程；二维码登录只能从已鉴权管理页或 Runtime API 显式发起。
- 每个微信帐号绑定一个逻辑 QQ 身份，共享私聊权限、历史、认知记忆和模型偏好；物理回复地址为 `wechat:<逻辑QQ号>`。
- `messages.send_voice` 可将音频附件显式发送为原生语音；WAV 等源音频由 FFmpeg 归一化并编码为 Tencent SILK，因此部署机需在 `PATH` 中提供 `ffmpeg`。普通附件标签不会自动改成语音。
- iLink 没有 QQ 合并转发卡片的协议合同。默认开启的多项目模式会把转发节点按原顺序放入一个或多个 `sendmessage.item_list` 请求；上游明确拒绝该结构时自动回退逐段发送，超时等结果不确定的失败不会重发，以免重复消息。可通过 `multi_item_messages_enabled=false` 强制使用逐段模式。
- 未匹配来源在进入命令、历史和 AI 前隔离，隔离记录不保存正文。
- `state_dir` 中包含登录凭据，不应提交到版本库或通过静态文件服务暴露。

详见 [微信 iLink 接入](wechat-ilink.md)。

---

### 4.25 `[api]` Runtime API / OpenAPI

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `enabled` | `true` | 是否启用主进程 Runtime API |
| `host` | `127.0.0.1` | Runtime API 监听地址 |
| `port` | `8788` | Runtime API 端口（1..65535） |
| `auth_key` | `changeme` | 请求头鉴权密钥（`X-Undefined-API-Key`） |
| `openapi_enabled` | `true` | 是否暴露 `/openapi.json` |
| `tool_invoke_callback_use_proxy` | `false` | Runtime tool invoke 回调外部 URL 时是否使用 `[proxy]` 中的代理地址 |

关键行为：
- Runtime API 仅在主进程 `Undefined` 中启动，WebUI 通过后端代理调用。
- WebUI 会自动读取 `config.toml` 的 `api.auth_key` 并转发，不在前端暴露密钥。
- 默认密钥 `changeme` 仅用于初始开发环境，生产请务必替换。

详见 [docs/openapi.md](openapi.md)。

---

### 4.26 `[cognitive]` 认知记忆

### 4.26.1 根配置

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `enabled` | `true` | 开启认知记忆 |
| `bot_name` | `Undefined` | 史官改写中使用的 bot 名称 |

### 4.26.2 `[cognitive.vector_store]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `path` | `data/cognitive/chromadb` | Chroma 存储目录 |
| `scheduler_foreground_burst` | `8` | Chroma 前台连续处理上限；达到后若有维护/后台任务，会让出一次执行机会。需重启 |

### 4.26.3 `[cognitive.query]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `auto_top_k` | `3` | 自动注入召回条数 |
| `auto_scope_candidate_multiplier` | `2` | 自动注入时每个作用域候选扩展倍数（候选数≈`auto_top_k * multiplier`） |
| `auto_current_group_boost` | `1.15` | 群聊自动检索时，当前群命中额外加权系数 |
| `auto_current_private_boost` | `1.25` | 私聊自动检索时，当前私聊命中额外加权系数 |
| `enable_rerank` | `true` | 认知检索是否启用 rerank；自动注入的多消息批次会先逐条召回，再用整批 query 做最终重排 |
| `recent_end_summaries_inject_k` | `30` | 最近 end 摘要注入条数，`0` 禁用 |
| `time_decay_enabled` | `true` | 是否启用时间衰减加权 |
| `time_decay_half_life_days_auto` | `14.0` | 自动注入场景半衰期 |
| `time_decay_half_life_days_tool` | `60.0` | 工具检索场景半衰期 |
| `time_decay_boost` | `0.2` | 时间加权强度 |
| `time_decay_min_similarity` | `0.35` | 应用时间加权的相似度阈值 |
| `tool_default_top_k` | `12` | 工具调用默认 top-k |
| `profile_top_k` | `8` | 侧写检索 top-k |
| `rerank_candidate_multiplier` | `3` | 候选倍数（`top_k * multiplier`） |

### 4.26.4 `[cognitive.historian]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `rewrite_max_retry` | `2` | 绝对化改写最大重试 |
| `recent_messages_inject_k` | `12` | 注入给史官的近期消息条数 |
| `recent_message_line_max_len` | `240` | 每条近期消息最大字符数 |
| `source_message_max_len` | `800` | 当前触发消息最大字符数 |
| `poll_interval_seconds` | `1.0` | 队列轮询间隔；小于 `0.1` 时按 `0.1` 秒处理，避免空队列忙循环 |
| `stale_job_timeout_seconds` | `300.0` | processing 超时回收阈值 |

### 4.26.5 `[cognitive.profile]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `path` | `data/cognitive/profiles` | 侧写存储目录 |
| `revision_keep` | `5` | 保留历史版本数量 |

### 4.26.6 `[cognitive.queue]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `path` | `data/cognitive/queues` | 队列目录 |
| `failed_max_age_days` | `30` | failed 文件保留天数 |
| `failed_max_files` | `500` | failed 文件上限 |
| `failed_cleanup_interval` | `100` | 每派发多少个任务后触发一次清理；`0` 禁用 |
| `job_max_retries` | `3` | 单任务自动重试次数 |

---

### 4.27 `[memes]` 表情包库

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `enabled` | `true` | 是否启用全局表情包库 | 关闭后不会自动入库，也无法使用 `memes.*` 工具 |
| `query_default_mode` | `"hybrid"` | 默认检索模式：`keyword` / `semantic` / `hybrid` | 非法值按 `hybrid` 处理 |
| `max_source_image_bytes` | `512000` | 入库前允许处理的原始图片大小上限（字节） | `<=0` 回退 `512000` |
| `blob_dir` | `data/memes/blobs` | 原图持久化目录 | 路径变更建议重启 |
| `preview_dir` | `data/memes/previews` | 预览图目录（GIF 抽首帧） | 路径变更建议重启 |
| `db_path` | `data/memes/memes.sqlite3` | SQLite 元数据路径 | 路径变更建议重启 |
| `vector_store_path` | `data/memes/chromadb` | Chroma 向量索引目录 | 路径变更建议重启 |
| `queue_path` | `data/memes/queues` | 后台任务队列目录 | 路径变更建议重启 |
| `max_items` | `10000` | 表情包条目上限 | `<=0` 回退 `10000` |
| `max_total_bytes` | `5368709120` | 表情包总磁盘占用上限（字节） | `<=0` 回退 `5368709120` |
| `allow_gif` | `true` | 是否允许 GIF 入库 | |
| `gif_analysis_mode` | `"grid"` | GIF 动图判定分析模式：`"grid"` (网格拼图)、`"multi"` (多图逐帧)、`"first_frame"` (仅第一帧) | 非法值回退 `"grid"` |
| `gif_analysis_frames` | `6` | GIF 动图抽帧供模型识别的数量 | `<=0` 回退 `6` |
| `auto_ingest_group` | `true` | 是否自动处理群聊图片 | |
| `auto_ingest_private` | `true` | 是否自动处理私聊图片 | |
| `keyword_top_k` | `30` | 关键词候选召回数 | `<=0` 回退 `30` |
| `semantic_top_k` | `30` | 语义候选召回数 | `<=0` 回退 `30` |
| `rerank_top_k` | `20` | 重排候选数 | `<=0` 回退 `20` |

说明：
- 表情包入库走两阶段 LLM 管线：
  1. 判定是否为表情包
  2. 对通过判定的图片生成纯文本描述与标签
- 第一阶段失败时，按“不是表情包”处理，直接丢弃（如果是网络和服务器限流等异常，系统会在后台自动重试）。
- 对于 GIF 格式图片的分析，`"grid"` 模式会将多个抽帧横向并排或拼接在一张大图中降低计费单元，`"multi"` 模式则将各帧作为独立图像输入至多模态大模型。
- 第二阶段不做 OCR；向量存储和检索文本只使用纯文本 `description + tags + aliases`。
- 同一图片内容在单进程内会按 `SHA256` 串行入库，避免并发表情包重复写入。
- 若入库在写入来源记录或向量索引阶段失败，会回滚已写入的元数据与本地文件，避免残留孤儿记录。
- 表情包与普通图片复用同一套图片 `uid` 语义。检索返回的 `uid` 既可用于 `memes.send_meme_by_uid`，也可直接用于 `<attachment uid="..."/>`。
- 检索模式：
  - `keyword`：只跑 SQLite FTS / LIKE 关键词检索；按空白切分后的中文、英文关键词都会参与 FTS 匹配
  - `semantic`：只跑 Chroma 语义检索
  - `hybrid`：关键词与语义同时召回，再合并并按配置重排
- 关键词检索会按空白切分查询词项并构造 FTS phrase，因此中文标签、别名或描述词同样可以走 FTS 召回。
- `query_default_mode` 只影响 `memes.search_memes` 未显式传 `query_mode` 时的默认值。

### 4.28 `[naga]` Naga 外部网关集成

> **⚠️ 此功能面向与 NagaAgent 对接的高级场景，普通用户不建议开启。**

启用后允许 NagaAgent 通过绑定审批机制向 QQ 群/用户发送回调消息。共享密钥统一使用 `Authorization: Bearer {naga.api_key}`，其中 `messages/send` 与 `unbind` 还会额外校验 `bind_uuid + naga_id + delivery_signature`。

**开关分层**：

| 开关 | 控制范围 | 默认值 |
|------|---------|--------|
| `[features].nagaagent_mode_enabled` | 进程总闸：是否具备 NagaAgent AI 能力（提示词/工具） | `false` |
| `[naga].enabled` | 进程总闸：外部网关集成（回调 API、`/naga` 命令、绑定管理） | `false` |
| `[naga].mode` + 群/私聊名单 | 会话级策略：在总闸打开后决定具体群/私聊是否启用 | `off` |

- 仅当 `[api].enabled = true`、`[features].nagaagent_mode_enabled = true`、`[naga].enabled = true` 三者同时成立时，外部网关**端点注册**才会生效
- 若只需 NagaAgent 解答能力而不需要外部回调联动，可只开启 `nagaagent_mode_enabled`
- `nagaagent_mode_enabled = false` 时强制关闭所有 Naga 功能，无论 `naga.enabled` 与名单配置
- AI 侧（提示词 / `naga_code_analysis_agent`）与外部网关（`/naga`、绑定、投递）共用同一套 `mode` 名单
- 会话策略语义对齐 `[access]`，详见 [access-control.md](access-control.md)

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `enabled` | `false` | 是否启用外部网关集成 | 需同时开启 `nagaagent_mode_enabled` |
| `api_url` | `""` | Naga 服务器 API 地址 | 为空时无法向远端提交 bind request / revoke 同步 |
| `api_key` | `""` | Undefined ↔ Naga 共享密钥 | 回调端点通过 `Authorization: Bearer` 校验 |
| `use_proxy` | `false` | 向 Naga 服务器发起外部请求时是否使用 `[proxy]` 中的代理地址 | |
| `moderation_enabled` | `true` | 是否启用 Naga 外发消息审核 | 关闭后 `messages/send` 直接跳过审核，返回 `moderation.status=skipped_disabled` |
| `mode` | `"off"` | 会话级策略：`off` / `blacklist` / `allowlist` | 非法值回退 `off` |
| `allowed_group_ids` | `[]` | 群白名单 | 仅 `allowlist` 生效；**空 = 拒绝全部群**（fail closed，比 `[access]` 更严） |
| `blocked_group_ids` | `[]` | 群黑名单 | 仅 `blacklist` 生效 |
| `allowed_private_ids` | `[]` | 私聊白名单 | 仅 `allowlist` 生效；**空 = 拒绝全部私聊**（fail closed） |
| `blocked_private_ids` | `[]` | 私聊黑名单 | 仅 `blacklist` 生效 |

**会话策略规则**：
- `mode=off`：不按名单过滤；总闸打开后所有群/私聊会话可用对应能力
- `mode=blacklist`：仅拦截 `blocked_group_ids` / `blocked_private_ids`
- `mode=allowlist`：仅放行 `allowed_*`；某维度列表为空表示该维度**全部拒绝**（fail closed）
- 私聊名单判定：调用方若将当前用户识别为 superadmin，则绕过私聊名单（当前实现固定如此，**不是** `[access].superadmin_bypass_*` 开关）；群聊无 superadmin 绕过
- 策略拒绝时的表现因入口而异：
  - 斜杠命令 `/naga`：命令不可见且静默忽略（`/help` 也不展示），**不**返回 HTTP 错误
  - Runtime API `/api/v1/naga/*`（如 `messages/send`）：HTTP 403，错误信息 `naga policy denied`
- `/api/v1/naga/*` 端点仅在 `api.enabled`、`nagaagent_mode_enabled`、`naga.enabled` 三者均开启时注册（进程级）
- Runtime API 关闭时，`/naga` 命令也不会在 `/help` 中显示

**兼容迁移**：
- 旧字段 `allowed_groups` 仍可读取，会合并进 `allowed_group_ids` 并打印弃用警告
- 若未显式配置 `mode` 但存在 `allowed_groups`，自动设为 `mode=allowlist`
- 注意：旧版空 `allowed_groups` 与当前 `allowlist` + 空 `allowed_group_ids` 均拒绝全部群；若需全部放行请使用 `mode=off`

**数据存储**：绑定数据持久化在 `data/naga_bindings.json`，Unix 下自动 `chmod 600`。

`naga.*` 变更需要重启进程才能生效。

---

## 6. 热更新与重启边界

### 5.1 热更新监听对象
- `config.toml`
- `config.local.json`

### 5.2 明确“需重启”的字段
以下变更会被记录为“需重启生效”：
- `logging.level`
- `logging.file_path`
- `logging.max_size_mb`
- `logging.backup_count`
- `logging.tty_enabled`
- `onebot.ws_url`
- `onebot.token`
- `webui.url`
- `webui.port`
- `webui.password`
- `webui.autostart_bot`
- `api.*`（`enabled/host/port/auth_key/openapi_enabled`）
- `memes.blob_dir`
- `memes.preview_dir`
- `memes.db_path`
- `memes.vector_store_path`
- `memes.queue_path`
- `naga.*`（`enabled/api_url/api_key/use_proxy/moderation_enabled/mode/allowed_group_ids/blocked_group_ids/allowed_private_ids/blocked_private_ids`）

### 5.3 明确“会执行热应用”的字段
- 模型发车间隔 / 模型名 / 模型池变更（队列间隔刷新）
- `models.grok.model_name` / `models.grok.queue_interval_seconds`（队列间隔刷新）
- `models.summary` / `models.historian` / `models.grok` 的非队列字段会刷新 AI 运行时配置，但不会重建聊天、视觉或 Agent 模型客户端；其中 `models.summary` 热更新会重建摘要服务，`/summary`/`/sum`、SummaryService（如 `/bugfix`）会立即使用专用 summary 模型配置；主 AI 调用的 `summary_agent` 始终走 `models.agent`（及 agent 模型池）。

#### 消息总结模型路由（易混淆）

| 入口 | 使用的模型配置 | 是否走 Agent / 工具 |
|------|----------------|---------------------|
| `/summary`、`/sum` 斜杠命令 | `[models.summary]`，未配置时回退 `[models.agent]` | 否：程序拉取历史后直连 summary 模型（队列 `call_type=message_summary`） |
| 主 AI 调用 `summary_agent` | `[models.agent]`（及 agent 模型池） | 是：Agent 通过 `fetch_messages` 工具拉取后再总结 |
| `/bugfix` 等使用 `SummaryService` 的路径 | 同 `/summary`（summary 模型） | 否 |

因此：**单独配置 `[models.summary]` 只影响斜杠命令与 SummaryService，不会改变主 AI 对话里 `summary_agent` 的行为。** 若希望对话内总结也使用专用模型，需调整 `[models.agent]` 或模型池，而不是只改 `[models.summary]`。
- `render.browser_max_concurrency` 会在当前渲染任务空闲后重建渲染并发信号量。
- `skills.intro_autogen_*`（Agent intro 生成器配置刷新）
- `skills.tool_search_*`（主 AI 后续新 `ask()` 的按需工具加载配置刷新）
- `lxmusic2api.base_url` / `lxmusic2api.api_key`（后续音乐请求与 `music.*` 工具可见性刷新）
- `search.searxng_url`（搜索客户端刷新）
- `search.priority` / `search.grok_search_enabled` / `search.firecrawl_search_enabled` / `search.firecrawl.*` 会随运行时配置更新，用于后续 `web_agent` 工具暴露和提示词优先级；无需重启。
- `api.tool_invoke_callback_use_proxy` 会随运行时配置更新，用于后续 Runtime tool invoke 回调。
- 各功能段与模型段的 `use_proxy` 会随运行时配置更新；模型 requester 会清理 client cache，后续请求按新的开关与 `[proxy]` 地址选择连接方式。
- `skills.hot_reload*`（技能热重载任务重启）
- `skills.hot_reload_interval/debounce`（配置热更新监听器自身重启）

### 5.4 其他字段
- `Config` 对象本身会更新。
- 具体功能是否“立刻体现”，取决于模块是“每次读取配置”还是“启动时缓存”。
- 对于行为不确定项，建议改完观察日志；必要时重启进程确认。

---

## 7. 兼容旧字段与隐藏字段

- `models.<x>.deepseek_new_cot_support`：旧 thinking 兼容开关。
- `[core].keyword_reply_enabled`：旧位置，建议迁移到 `[easter_egg]`。
- `[bilibili].sessdata`：旧字段，建议改为完整 `cookie`。
- `[proxy].use_proxy` / `USE_PROXY`：已移除；请改用各功能段或模型段下的 `use_proxy`，默认均为 `false`。
- `api_endpoints.jkyai_base_url`、`api_endpoints.seniverse_base_url`、`weather.api_key`：代码仍支持，模板中未显式列出。

---

## 8. 环境变量兜底（迁移建议）

虽然推荐统一写入 `config.toml`，当前仍支持环境变量兜底。规则：

1. **仅当 TOML / `from_mapping` 未提供对应项** 时读取环境变量。
2. 检测到 env 兜底时可能输出 `[配置]` 告警，建议迁移到 TOML。
3. 主注册表由 `src/Undefined/config/env_registry.py` 维护；变更注册表时请同步更新本节表格。

<!-- env-registry:begin -->

以下环境变量在 **TOML 对应项缺失** 时作为兜底读取。
完整注册表见 `src/Undefined/config/env_registry.py`。

#### `access`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `access.allowed_group_ids` | `ALLOWED_GROUP_IDS` |
| `access.allowed_private_ids` | `ALLOWED_PRIVATE_IDS` |
| `access.blocked_group_ids` | `BLOCKED_GROUP_IDS` |
| `access.blocked_private_ids` | `BLOCKED_PRIVATE_IDS` |
| `access.mode` | `ACCESS_MODE` |

#### `api`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `api.tool_invoke_callback_use_proxy` | `API_TOOL_INVOKE_CALLBACK_USE_PROXY` |

#### `api_endpoints`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `api_endpoints.jkyai_base_url` | `JKYAI_BASE_URL` |
| `api_endpoints.xxapi_base_url` | `XXAPI_BASE_URL` |

#### `attachments`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `attachments.use_proxy` | `ATTACHMENTS_USE_PROXY` |

#### `arxiv`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `arxiv.use_proxy` | `ARXIV_USE_PROXY` |

#### `bilibili`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `bilibili.use_proxy` | `BILIBILI_USE_PROXY` |

#### `core`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `core.admin_qq` | `ADMIN_QQ` |
| `core.bot_qq` | `BOT_QQ` |
| `core.forward_proxy_qq` | `FORWARD_PROXY_QQ` |
| `core.superadmin_qq` | `SUPERADMIN_QQ` |

#### `features`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `features.pool_enabled` | `MODEL_POOL_ENABLED` |

#### `github`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `github.use_proxy` | `GITHUB_USE_PROXY` |

#### `history`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `history.max_records` | `HISTORY_MAX_RECORDS` |

#### `image_gen`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `image_gen.provider` | `IMAGE_GEN_PROVIDER` |
| `image_gen.use_proxy` | `IMAGE_GEN_USE_PROXY` |

#### `logging`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `logging.backup_count` | `LOG_BACKUP_COUNT` |
| `logging.file_path` | `LOG_FILE_PATH` |
| `logging.level` | `LOG_LEVEL` |
| `logging.log_thinking` | `LOG_THINKING` |
| `logging.max_size_mb` | `LOG_MAX_SIZE_MB` |
| `logging.tty_enabled` | `LOG_TTY_ENABLED` |

#### `mcp`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `mcp.config_path` | `MCP_CONFIG_PATH` |

#### `models.agent`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `models.agent.api_key` | `AGENT_MODEL_API_KEY` |
| `models.agent.api_mode` | `AGENT_MODEL_API_MODE` |
| `models.agent.api_url` | `AGENT_MODEL_API_URL` |
| `models.agent.context_window_tokens` | `AGENT_MODEL_CONTEXT_WINDOW_TOKENS` |
| `models.agent.max_tokens` | `AGENT_MODEL_MAX_TOKENS` |
| `models.agent.model_name` | `AGENT_MODEL_NAME` |
| `models.agent.prompt_cache_enabled` | `AGENT_MODEL_PROMPT_CACHE_ENABLED` |
| `models.agent.queue_interval_seconds` | `AGENT_MODEL_QUEUE_INTERVAL` |
| `models.agent.reasoning_effort` | `AGENT_MODEL_REASONING_EFFORT` |
| `models.agent.reasoning_enabled` | `AGENT_MODEL_REASONING_ENABLED` |
| `models.agent.stream_enabled` | `AGENT_MODEL_STREAM_ENABLED` |
| `models.agent.thinking_budget_tokens` | `AGENT_MODEL_THINKING_BUDGET_TOKENS` |
| `models.agent.thinking_enabled` | `AGENT_MODEL_THINKING_ENABLED` |
| `models.agent.thinking_include_budget` | `AGENT_MODEL_THINKING_INCLUDE_BUDGET` |
| `models.agent.thinking_param_enabled` | `AGENT_MODEL_THINKING_PARAM_ENABLED` |
| `models.agent.thinking_tool_call_compat` | `AGENT_MODEL_THINKING_TOOL_CALL_COMPAT` |
| `models.agent.use_proxy` | `AGENT_MODEL_USE_PROXY` |
| `models.agent.reasoning_content_replay` | `AGENT_MODEL_REASONING_CONTENT_REPLAY` |
| `models.agent.responses_force_stateless_replay` | `AGENT_MODEL_RESPONSES_FORCE_STATELESS_REPLAY` |
| `models.agent.responses_tool_choice_compat` | `AGENT_MODEL_RESPONSES_TOOL_CHOICE_COMPAT` |
| `models.agent.system_prompt_as_user` | `AGENT_MODEL_SYSTEM_PROMPT_AS_USER` |

#### `models.chat`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `models.chat.api_key` | `CHAT_MODEL_API_KEY` |
| `models.chat.api_mode` | `CHAT_MODEL_API_MODE` |
| `models.chat.api_url` | `CHAT_MODEL_API_URL` |
| `models.chat.context_window_tokens` | `CHAT_MODEL_CONTEXT_WINDOW_TOKENS` |
| `models.chat.max_tokens` | `CHAT_MODEL_MAX_TOKENS` |
| `models.chat.model_name` | `CHAT_MODEL_NAME` |
| `models.chat.prompt_cache_enabled` | `CHAT_MODEL_PROMPT_CACHE_ENABLED` |
| `models.chat.queue_interval_seconds` | `CHAT_MODEL_QUEUE_INTERVAL` |
| `models.chat.reasoning_effort` | `CHAT_MODEL_REASONING_EFFORT` |
| `models.chat.reasoning_enabled` | `CHAT_MODEL_REASONING_ENABLED` |
| `models.chat.stream_enabled` | `CHAT_MODEL_STREAM_ENABLED` |
| `models.chat.thinking_budget_tokens` | `CHAT_MODEL_THINKING_BUDGET_TOKENS` |
| `models.chat.thinking_enabled` | `CHAT_MODEL_THINKING_ENABLED` |
| `models.chat.thinking_include_budget` | `CHAT_MODEL_THINKING_INCLUDE_BUDGET` |
| `models.chat.thinking_param_enabled` | `CHAT_MODEL_THINKING_PARAM_ENABLED` |
| `models.chat.thinking_tool_call_compat` | `CHAT_MODEL_THINKING_TOOL_CALL_COMPAT` |
| `models.chat.use_proxy` | `CHAT_MODEL_USE_PROXY` |
| `models.chat.reasoning_content_replay` | `CHAT_MODEL_REASONING_CONTENT_REPLAY` |
| `models.chat.responses_force_stateless_replay` | `CHAT_MODEL_RESPONSES_FORCE_STATELESS_REPLAY` |
| `models.chat.responses_tool_choice_compat` | `CHAT_MODEL_RESPONSES_TOOL_CHOICE_COMPAT` |
| `models.chat.system_prompt_as_user` | `CHAT_MODEL_SYSTEM_PROMPT_AS_USER` |

#### `models.embedding`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `models.embedding.api_key` | `EMBEDDING_MODEL_API_KEY` |
| `models.embedding.api_url` | `EMBEDDING_MODEL_API_URL` |
| `models.embedding.context_window_tokens` | `EMBEDDING_MODEL_CONTEXT_WINDOW_TOKENS` |
| `models.embedding.model_name` | `EMBEDDING_MODEL_NAME` |
| `models.embedding.use_proxy` | `EMBEDDING_MODEL_USE_PROXY` |

#### `models.grok`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `models.grok.api_key` | `GROK_MODEL_API_KEY` |
| `models.grok.api_mode` | `GROK_MODEL_API_MODE` |
| `models.grok.api_url` | `GROK_MODEL_API_URL` |
| `models.grok.context_window_tokens` | `GROK_MODEL_CONTEXT_WINDOW_TOKENS` |
| `models.grok.max_tokens` | `GROK_MODEL_MAX_TOKENS` |
| `models.grok.model_name` | `GROK_MODEL_NAME` |
| `models.grok.prompt_cache_enabled` | `GROK_MODEL_PROMPT_CACHE_ENABLED` |
| `models.grok.queue_interval_seconds` | `GROK_MODEL_QUEUE_INTERVAL` |
| `models.grok.reasoning_content_replay` | `GROK_MODEL_REASONING_CONTENT_REPLAY` |
| `models.grok.reasoning_effort` | `GROK_MODEL_REASONING_EFFORT` |
| `models.grok.reasoning_enabled` | `GROK_MODEL_REASONING_ENABLED` |
| `models.grok.responses_force_stateless_replay` | `GROK_MODEL_RESPONSES_FORCE_STATELESS_REPLAY` |
| `models.grok.responses_tool_choice_compat` | `GROK_MODEL_RESPONSES_TOOL_CHOICE_COMPAT` |
| `models.grok.stream_enabled` | `GROK_MODEL_STREAM_ENABLED` |
| `models.grok.system_prompt_as_user` | `GROK_MODEL_SYSTEM_PROMPT_AS_USER` |
| `models.grok.thinking_budget_tokens` | `GROK_MODEL_THINKING_BUDGET_TOKENS` |
| `models.grok.thinking_enabled` | `GROK_MODEL_THINKING_ENABLED` |
| `models.grok.thinking_include_budget` | `GROK_MODEL_THINKING_INCLUDE_BUDGET` |
| `models.grok.thinking_param_enabled` | `GROK_MODEL_THINKING_PARAM_ENABLED` |
| `models.grok.thinking_tool_call_compat` | `GROK_MODEL_THINKING_TOOL_CALL_COMPAT` |
| `models.grok.use_proxy` | `GROK_MODEL_USE_PROXY` |

#### `models.historian`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `models.historian.use_proxy` | `HISTORIAN_MODEL_USE_PROXY` |
| `models.historian.reasoning_content_replay` | `HISTORIAN_MODEL_REASONING_CONTENT_REPLAY` |
| `models.historian.system_prompt_as_user` | `HISTORIAN_MODEL_SYSTEM_PROMPT_AS_USER` |
| `models.historian.thinking_param_enabled` | `HISTORIAN_MODEL_THINKING_PARAM_ENABLED` |

#### `models.image_edit`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `models.image_edit.use_proxy` | `IMAGE_EDIT_MODEL_USE_PROXY` |

#### `models.image_gen`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `models.image_gen.use_proxy` | `IMAGE_GEN_MODEL_USE_PROXY` |

#### `models.naga`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `models.naga.api_key` | `NAGA_MODEL_API_KEY` |
| `models.naga.api_mode` | `NAGA_MODEL_API_MODE` |
| `models.naga.api_url` | `NAGA_MODEL_API_URL` |
| `models.naga.context_window_tokens` | `NAGA_MODEL_CONTEXT_WINDOW_TOKENS` |
| `models.naga.max_tokens` | `NAGA_MODEL_MAX_TOKENS` |
| `models.naga.model_name` | `NAGA_MODEL_NAME` |
| `models.naga.prompt_cache_enabled` | `NAGA_MODEL_PROMPT_CACHE_ENABLED` |
| `models.naga.queue_interval_seconds` | `NAGA_MODEL_QUEUE_INTERVAL` |
| `models.naga.reasoning_effort` | `NAGA_MODEL_REASONING_EFFORT` |
| `models.naga.reasoning_enabled` | `NAGA_MODEL_REASONING_ENABLED` |
| `models.naga.stream_enabled` | `NAGA_MODEL_STREAM_ENABLED` |
| `models.naga.thinking_budget_tokens` | `NAGA_MODEL_THINKING_BUDGET_TOKENS` |
| `models.naga.thinking_enabled` | `NAGA_MODEL_THINKING_ENABLED` |
| `models.naga.thinking_include_budget` | `NAGA_MODEL_THINKING_INCLUDE_BUDGET` |
| `models.naga.thinking_param_enabled` | `NAGA_MODEL_THINKING_PARAM_ENABLED` |
| `models.naga.thinking_tool_call_compat` | `NAGA_MODEL_THINKING_TOOL_CALL_COMPAT` |
| `models.naga.use_proxy` | `NAGA_MODEL_USE_PROXY` |
| `models.naga.reasoning_content_replay` | `NAGA_MODEL_REASONING_CONTENT_REPLAY` |
| `models.naga.responses_force_stateless_replay` | `NAGA_MODEL_RESPONSES_FORCE_STATELESS_REPLAY` |
| `models.naga.responses_tool_choice_compat` | `NAGA_MODEL_RESPONSES_TOOL_CHOICE_COMPAT` |
| `models.naga.system_prompt_as_user` | `NAGA_MODEL_SYSTEM_PROMPT_AS_USER` |

#### `models.rerank`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `models.rerank.api_key` | `RERANK_MODEL_API_KEY` |
| `models.rerank.api_url` | `RERANK_MODEL_API_URL` |
| `models.rerank.context_window_tokens` | `RERANK_MODEL_CONTEXT_WINDOW_TOKENS` |
| `models.rerank.model_name` | `RERANK_MODEL_NAME` |
| `models.rerank.use_proxy` | `RERANK_MODEL_USE_PROXY` |

#### `models.security`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `models.security.api_key` | `SECURITY_MODEL_API_KEY` |
| `models.security.api_mode` | `SECURITY_MODEL_API_MODE` |
| `models.security.api_url` | `SECURITY_MODEL_API_URL` |
| `models.security.context_window_tokens` | `SECURITY_MODEL_CONTEXT_WINDOW_TOKENS` |
| `models.security.max_tokens` | `SECURITY_MODEL_MAX_TOKENS` |
| `models.security.model_name` | `SECURITY_MODEL_NAME` |
| `models.security.prompt_cache_enabled` | `SECURITY_MODEL_PROMPT_CACHE_ENABLED` |
| `models.security.queue_interval_seconds` | `SECURITY_MODEL_QUEUE_INTERVAL` |
| `models.security.reasoning_effort` | `SECURITY_MODEL_REASONING_EFFORT` |
| `models.security.reasoning_enabled` | `SECURITY_MODEL_REASONING_ENABLED` |
| `models.security.stream_enabled` | `SECURITY_MODEL_STREAM_ENABLED` |
| `models.security.thinking_budget_tokens` | `SECURITY_MODEL_THINKING_BUDGET_TOKENS` |
| `models.security.thinking_enabled` | `SECURITY_MODEL_THINKING_ENABLED` |
| `models.security.thinking_include_budget` | `SECURITY_MODEL_THINKING_INCLUDE_BUDGET` |
| `models.security.thinking_param_enabled` | `SECURITY_MODEL_THINKING_PARAM_ENABLED` |
| `models.security.thinking_tool_call_compat` | `SECURITY_MODEL_THINKING_TOOL_CALL_COMPAT` |
| `models.security.use_proxy` | `SECURITY_MODEL_USE_PROXY` |
| `models.security.reasoning_content_replay` | `SECURITY_MODEL_REASONING_CONTENT_REPLAY` |
| `models.security.responses_force_stateless_replay` | `SECURITY_MODEL_RESPONSES_FORCE_STATELESS_REPLAY` |
| `models.security.responses_tool_choice_compat` | `SECURITY_MODEL_RESPONSES_TOOL_CHOICE_COMPAT` |
| `models.security.system_prompt_as_user` | `SECURITY_MODEL_SYSTEM_PROMPT_AS_USER` |

#### `models.vision`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `models.vision.api_key` | `VISION_MODEL_API_KEY` |
| `models.vision.api_mode` | `VISION_MODEL_API_MODE` |
| `models.vision.api_url` | `VISION_MODEL_API_URL` |
| `models.vision.context_window_tokens` | `VISION_MODEL_CONTEXT_WINDOW_TOKENS` |
| `models.vision.max_tokens` | `VISION_MODEL_MAX_TOKENS` |
| `models.vision.model_name` | `VISION_MODEL_NAME` |
| `models.vision.prompt_cache_enabled` | `VISION_MODEL_PROMPT_CACHE_ENABLED` |
| `models.vision.queue_interval_seconds` | `VISION_MODEL_QUEUE_INTERVAL` |
| `models.vision.reasoning_effort` | `VISION_MODEL_REASONING_EFFORT` |
| `models.vision.reasoning_enabled` | `VISION_MODEL_REASONING_ENABLED` |
| `models.vision.stream_enabled` | `VISION_MODEL_STREAM_ENABLED` |
| `models.vision.thinking_budget_tokens` | `VISION_MODEL_THINKING_BUDGET_TOKENS` |
| `models.vision.thinking_enabled` | `VISION_MODEL_THINKING_ENABLED` |
| `models.vision.thinking_include_budget` | `VISION_MODEL_THINKING_INCLUDE_BUDGET` |
| `models.vision.thinking_param_enabled` | `VISION_MODEL_THINKING_PARAM_ENABLED` |
| `models.vision.thinking_tool_call_compat` | `VISION_MODEL_THINKING_TOOL_CALL_COMPAT` |
| `models.vision.use_proxy` | `VISION_MODEL_USE_PROXY` |
| `models.vision.reasoning_content_replay` | `VISION_MODEL_REASONING_CONTENT_REPLAY` |
| `models.vision.responses_force_stateless_replay` | `VISION_MODEL_RESPONSES_FORCE_STATELESS_REPLAY` |
| `models.vision.responses_tool_choice_compat` | `VISION_MODEL_RESPONSES_TOOL_CHOICE_COMPAT` |
| `models.vision.system_prompt_as_user` | `VISION_MODEL_SYSTEM_PROMPT_AS_USER` |

#### `models.summary`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `models.summary.use_proxy` | `SUMMARY_MODEL_USE_PROXY` |
| `models.summary.reasoning_content_replay` | `SUMMARY_MODEL_REASONING_CONTENT_REPLAY` |
| `models.summary.system_prompt_as_user` | `SUMMARY_MODEL_SYSTEM_PROMPT_AS_USER` |
| `models.summary.thinking_param_enabled` | `SUMMARY_MODEL_THINKING_PARAM_ENABLED` |

#### `messages`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `messages.use_proxy` | `MESSAGES_USE_PROXY` |

#### `lxmusic2api`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `lxmusic2api.api_key` | `LXMUSIC2API_API_KEY` |
| `lxmusic2api.base_url` | `LXMUSIC2API_BASE_URL` |

#### `naga`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `naga.use_proxy` | `NAGA_USE_PROXY` |

#### `onebot`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `onebot.token` | `ONEBOT_TOKEN` |
| `onebot.ws_url` | `ONEBOT_WS_URL` |

#### `render`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `render.browser_executable_path` | `RENDER_BROWSER_EXECUTABLE_PATH` |
| `render.long_image_default_padding` | `RENDER_LONG_IMAGE_DEFAULT_PADDING` |
| `render.long_image_default_width` | `RENDER_LONG_IMAGE_DEFAULT_WIDTH` |
| `render.use_proxy` | `RENDER_USE_PROXY` |

#### `search`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `search.use_proxy` | `SEARCH_USE_PROXY` |
| `search.priority` | `SEARCH_PRIORITY` |
| `search.searxng_url` | `SEARXNG_URL` |
| `search.firecrawl_search_enabled` | `FIRECRAWL_SEARCH_ENABLED` |
| `search.firecrawl.api_key` | `FIRECRAWL_API_KEY` |
| `search.firecrawl.base_url` | `FIRECRAWL_BASE_URL` |

#### `skills`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `skills.hot_reload` | `SKILLS_HOT_RELOAD` |
| `skills.intro_hash_path` | `AGENT_INTRO_HASH_PATH` |
| `skills.prefetch_tools_hide` | `PREFETCH_TOOLS_HIDE` |
| `skills.tool_search_always_loaded` | `TOOL_SEARCH_ALWAYS_LOADED` |
| `skills.tool_search_enabled` | `TOOL_SEARCH_ENABLED` |
| `skills.tool_search_max_results` | `TOOL_SEARCH_MAX_RESULTS` |

#### `token_usage`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `token_usage.max_archives` | `TOKEN_USAGE_MAX_ARCHIVES` |
| `token_usage.max_size_mb` | `TOKEN_USAGE_MAX_SIZE_MB` |
| `token_usage.max_total_mb` | `TOKEN_USAGE_MAX_TOTAL_MB` |

#### `tools`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `tools.description_max_len` | `TOOLS_DESCRIPTION_MAX_LEN` |
| `tools.dot_delimiter` | `TOOLS_DOT_DELIMITER` |
| `tools.sanitize_verbose` | `TOOLS_SANITIZE_VERBOSE` |

#### `weather`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `weather.api_key` | `WEATHER_API_KEY` |

#### `xxapi`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `xxapi.api_token` | `XXAPI_API_TOKEN` |

#### 备用 / 兼容环境变量

以下变量不在主注册表中，但在解析时仍会被读取：

| 环境变量 | 映射 TOML 路径 |
|----------|----------------|
| `EASTER_EGG_AGENT_CALL_MESSAGE_MODE` | `easter_egg.agent_call_message_enabled` |
| `EASTER_EGG_CALL_MESSAGE_MODE` | `easter_egg.agent_call_message_enabled` |
| `HTTPS_PROXY` | `proxy.https_proxy` |
| `HTTP_PROXY` | `proxy.http_proxy` |

<!-- env-registry:end -->

建议：

1. 把长期配置迁移到 `config.toml`。
2. 环境变量只保留临时覆写、CI 密钥或库嵌入场景的敏感项注入。

## 9. 运维建议（生产环境）

1. 首次部署先改 `webui.password`，避免默认密码模式。
2. 显式配置 `access.mode`，不要依赖 legacy 行为。
3. 启用 `knowledge`/`cognitive` 前先验证 embedding/rerank 配置是否齐全。
4. 若使用模型池，先确认 `features.pool_enabled=true`。
5. 修改 `onebot`、`logging`、`webui` 后直接重启。
6. 观察启动日志中的 `[配置]` 告警，优先处理“自动回退”信息。
