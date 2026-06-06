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

### 4.4.1 通用字段（chat/vision/security/agent/historian）

| 字段 | 含义 |
|---|---|
| `api_url` | OpenAI-compatible 基址（建议 `.../v1`） |
| `api_key` | API Key |
| `model_name` | 模型名 |
| `max_tokens` | 最大输出 token（vision 无此字段） |
| `context_window_tokens` | 模型上下文窗口上限（token），用于 `/summary` 分块与 Prompt 预算；解析默认 `8192`，须按上游模型能力配置 |
| `queue_interval_seconds` | 该模型请求队列发车间隔（秒，`0` 表示立即发车） |
| `api_mode` | 请求模式：`chat_completions` 或 `responses` |
| `reasoning_enabled` | 是否启用 `reasoning.effort` |
| `reasoning_effort` | `reasoning.effort` 档位：`none` / `minimal` / `low` / `medium` / `high` / `xhigh` |
| `thinking_enabled` | 是否启用旧式 `thinking` 参数 |
| `thinking_budget_tokens` | thinking 预算 |
| `thinking_include_budget` | 是否发送 `budget_tokens` |
| `thinking_tool_call_compat` | Tool Calls 兼容模式：在**本地历史**回填 `reasoning_content` / `_responses_output_items`（日志与回放）；**不**向上游续传；默认 `true` |
| `reasoning_content_replay` | 多轮工具调用时是否将 CoT **续传给上游**（Chat：`reasoning_content`；Responses：output items + `reasoning.encrypted_content`）；默认 `false` |
| `system_prompt_as_user` | 是否将所有 `system`/`developer` 消息合并注入首条 `user`（仅 `chat_completions`）；默认 `false` |
| `responses_tool_choice_compat` | `responses` 下的 `tool_choice` 兼容开关：仅建议在默认关闭时请求仍返回 500、怀疑上游不兼容对象型 `tool_choice` 时再尝试开启；开启后降级为字符串 `"required"`；默认 `false` |
| `responses_force_stateless_replay` | `responses` 下的续轮强制降级开关：启用后多轮工具调用始终跳过 `previous_response_id`，改为完整消息重放；默认 `false` |
| `prompt_cache_enabled` | 是否自动生成稳定的 `prompt_cache_key` 以提升相似请求缓存命中率；默认 `true` |
| `request_params` | 额外请求体参数（透传给模型 API，保留字段会忽略） |

请求模式说明：
- `api_mode="chat_completions"`：走 `client.chat.completions.create(...)`
  - `thinking_enabled=true` 时发送旧式 `thinking`
  - `reasoning_enabled=true` 时按 OpenAI 标准发送顶层 `reasoning_effort="..."`；仅 `reasoning_effort_style="anthropic"` 时改发 `output_config={ effort = ... }`
  - 默认（`reasoning_content_replay=false`）：`reasoning_content` 仅保存在本地历史，出站 Chat 请求会剥离该字段
  - `reasoning_content_replay=true` 时：多轮工具调用会在 Chat 出站消息中保留 `reasoning_content`；流式响应会累积 `delta.reasoning_content`
  - MiMo 等 thinking 模型常见组合：`api_mode=chat_completions` + `reasoning_content_replay=true`
- `api_mode="responses"`：走 `client.responses.create(...)`
  - 仅在 `reasoning_enabled=true` 时按 OpenAI 标准发送 `reasoning={ effort = ... }`
  - 若 `request_params` 里带 `response_format` / `verbosity`，会自动映射到 `text.format` / `text.verbosity`
  - 默认使用官方对象格式：`{"type":"function","name":"..."}`
  - `responses_tool_choice_compat=true` 时，会把指定函数的 `tool_choice` 降级为字符串 `"required"`，并只保留目标工具，用于兼容部分不完整代理
  - `responses_force_stateless_replay=true` 时，多轮工具调用会始终跳过 `previous_response_id`，直接走完整消息重放；续轮时会优先回放标准 `output` items（含 reasoning item），并自动补 `include=["reasoning.encrypted_content"]`
  - `reasoning_content_replay=true` 时，**首次** Responses 请求也会请求 `reasoning.encrypted_content`，便于后续 stateless replay；与 `responses_force_stateless_replay` 可组合使用（网关弱时建议同时开启后者）
  - Responses 工具续轮遵循 OpenAI 的标准字段语义：工具结果使用 `function_call_output.call_id` 关联前一轮工具调用；`function_call.id` 若存在，必须是模型生成的 output item id（通常为 `fc_*`），不能把 `call_*` 误写进 `id`
  - 仅建议在默认关闭时请求仍返回 500，再尝试开启这些兼容开关
  - 当前已知 `new-api v0.11.4-alpha.3` 存在这类兼容问题
  - 旧式 `thinking_*` 不会下发到 `responses`

Prompt caching 补充：
- 当 `prompt_cache_enabled=true` 且未显式设置 `prompt_cache_key` 时，运行时会按“模型名 + call_type + 会话作用域”自动生成稳定 key。
- 该 key 只用于提升路由稳定性，不改变 prompt 内容。
- 想提高缓存命中率时，仍应尽量把静态内容放前面、把高频变化内容放后面。

`request_params` 说明：
- 适合放 provider 私有请求体字段，例如 `metadata`、`temperature`、兼容网关扩展参数等。
- 不要再通过 `request_params` 传 `reasoning` / `reasoning_effort` / `thinking`；这些现在有正式配置字段控制。
- 消息总结分块读取 `[models.summary].context_window_tokens`（未单独配置时回退 `[models.agent]`）；不再使用硬编码窗口或 `request_params` 里的 `context_length` 类字段。

#### 思维链续传迁移说明

旧文档曾将 `thinking_tool_call_compat=true` 描述为“向上游回传 `reasoning_content`”。当前实现已拆分为两个独立开关：

| 开关 | 作用 |
|------|------|
| `thinking_tool_call_compat=true`（默认） | 多轮工具调用时在**本地历史**回填 `reasoning_content` / `_responses_output_items`，供日志与回放；**出站请求仍剥离**该字段 |
| `reasoning_content_replay=true`（默认 `false`） | 多轮工具调用时将 CoT **续传给上游**（Chat：`reasoning_content`；Responses：`reasoning.encrypted_content` 等） |

**升级建议**：
- 若你使用的 thinking 模型在多轮工具调用时返回 400，且错误提示缺少 `reasoning_content` / reasoning item，请在对应模型节开启 `reasoning_content_replay = true`。
- 仅需要本地调试/回放思维链、不希望增大上游 payload 时，保持 `reasoning_content_replay = false` 即可。
- MiMo / DeepSeek 等常见组合：`api_mode = "chat_completions"` + `reasoning_content_replay = true`（必要时叠加 `responses_force_stateless_replay = true`）。

兼容字段（旧配置）：
- `models.<x>.deepseek_new_cot_support`
  - 若开启：等效默认 `thinking_include_budget=false` + `thinking_tool_call_compat=true`
  - 显式设置新字段时，以新字段为准。

### 4.4.2 `[models.chat]` 主对话模型

默认：
- `max_tokens=8192`
- `queue_interval_seconds=1.0`（`0` 表示立即发车，`<0` 回退 `1.0`）
- `api_mode="chat_completions"`
- `reasoning_enabled=false`
- `reasoning_effort="medium"`
- `thinking_budget_tokens=20000`
- `thinking_tool_call_compat=true`
- `responses_tool_choice_compat=false`
- `responses_force_stateless_replay=false`

补充：
- 若上游只对 `/v1/responses` 识别自定义参数，可将 `api_mode` 切到 `responses`。
- `[models.chat.request_params]` 仍可放 `temperature`、`response_format`、`verbosity` 或兼容网关私有字段，但不再用于 `reasoning` 配置。

### 4.4.3 `[models.vision]` 视觉模型

默认：
- `queue_interval_seconds=1.0`（`0` 表示立即发车，`<0` 回退 `1.0`）
- `api_mode="chat_completions"`
- `reasoning_enabled=false`
- `reasoning_effort="medium"`
- `thinking_budget_tokens=20000`
- `thinking_tool_call_compat=true`
- `responses_tool_choice_compat=false`
- `responses_force_stateless_replay=false`

### 4.4.4 `[models.security]` 安全模型

字段：
- 额外开关：`enabled=true`
- 默认：`max_tokens=100`、`queue_interval_seconds=1.0`（`0` 表示立即发车，`<0` 回退 `1.0`）、`api_mode="chat_completions"`、`reasoning_enabled=false`、`reasoning_effort="medium"`、`thinking_budget_tokens=0`、`thinking_tool_call_compat=true`、`responses_tool_choice_compat=false`、`responses_force_stateless_replay=false`

关键回退逻辑：
- 若 `api_url/api_key/model_name` 任一缺失，会自动回退为 chat 模型（并告警）。
- 回退时会继承 chat 的 `api_mode`、`reasoning_*`、`responses_tool_choice_compat`、`responses_force_stateless_replay` 与 `request_params`；旧 `thinking_*` 仍保持安全模型自身默认值。

### 4.4.5 `[models.naga]` Naga 审核模型

用途：
- 仅用于 `POST /api/v1/naga/messages/send` 前的消息审核。

默认：
- `max_tokens=160`
- `queue_interval_seconds=1.0`（`0` 表示立即发车，`<0` 回退 `1.0`）
- `api_mode="chat_completions"`
- `reasoning_enabled=false`
- `reasoning_effort="medium"`
- `thinking_enabled=false`
- `thinking_budget_tokens=0`
- `thinking_include_budget=true`
- `thinking_tool_call_compat=true`
- `responses_tool_choice_compat=false`
- `responses_force_stateless_replay=false`

关键回退逻辑：
- 若整个节缺失或 `api_url/api_key/model_name` 任一缺失：完整回退到 `models.security`，并沿用安全模型的请求参数。

### 4.4.6 `[models.agent]` Agent 执行模型

默认：
- `max_tokens=4096`
- `queue_interval_seconds=1.0`（`0` 表示立即发车，`<0` 回退 `1.0`）
- `api_mode="chat_completions"`
- `reasoning_enabled=false`
- `reasoning_effort="medium"`
- `thinking_tool_call_compat=true`
- `responses_tool_choice_compat=false`
- `responses_force_stateless_replay=false`

### 4.4.7 `[models.historian]` 史官模型

- 用于认知记忆后台改写。
- 若整个节缺失或为空：完整回退到 `models.agent`。
- 若部分字段缺失：逐项继承 agent 配置，包括 `api_mode`、`reasoning_*`、`thinking_*`、`responses_tool_choice_compat`、`responses_force_stateless_replay` 与 `request_params`。
- `queue_interval_seconds=0` 时立即发车，`<0` 时回退到 agent 的间隔。

### 4.4.8 `[models.grok]` Grok 搜索模型

用途：
- 仅供 `web_agent` 内的 `grok_search` 子工具使用。
- 工具调用该模型时会注入专用 system prompt：以服务端当前时间作为“今天 / 最新 / 最近”的基准，要求先搜索、使用多组搜索查询或多个搜索工具、禁止编造，并在结果中给出来源。

默认：
- `max_tokens=8192`
- `queue_interval_seconds=1.0`（`0` 表示立即发车，`<0` 回退 `1.0`）
- 固定走 `chat_completions`
- `reasoning_enabled=false`
- `reasoning_effort="medium"`
- `thinking_enabled=false`
- `thinking_budget_tokens=20000`
- `thinking_include_budget=true`
- `reasoning_effort_style="openai"`

补充：
- 该模型节不提供 `api_mode`。
- 该模型节不提供 `thinking_tool_call_compat`、`responses_tool_choice_compat`、`responses_force_stateless_replay`。
- `[models.grok.request_params]` 的保留字段规则与 `chat_completions` 一致。

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
- `api_mode` / `reasoning_enabled` / `reasoning_effort` / `responses_tool_choice_compat` / `responses_force_stateless_replay`
- `thinking_*` / `request_params`
- 以上可选字段缺省继承主模型
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
| `queue_interval_seconds` | `0.0` | `0` 立即发车，`<0` 回退 `0.0` |
| `query_instruction` | `""` | 查询前缀 |
| `request_params` | `{}` | 额外请求体参数；保留字段如 `model`/`query`/`documents`/`top_n` 会忽略 |

`request_params` 说明：
- 仅用于**请求体**字段，不包含 `api_key`、`base_url`、`timeout`、`extra_headers` 等 client 选项。
- 聊天类（`chat_completions`）保留字段：`model`、`messages`、`max_tokens`、`tools`、`tool_choice`、`stream`、`stream_options`、`thinking`、`reasoning`、`reasoning_effort`、`output_config`。
- 聊天类（`responses`）保留字段：`model`、`input`、`instructions`、`max_output_tokens`、`tools`、`tool_choice`、`previous_response_id`、`stream`、`stream_options`、`thinking`、`reasoning`、`reasoning_effort`、`output_config`。启用 `responses_force_stateless_replay` 时会主动跳过 `previous_response_id`。历史 `output` items 由运行时自动维护；不要通过 `request_params` 手工注入或覆盖 `function_call.id` / `call_id`。
- 启用 `stream_enabled` 且使用 `chat_completions` 时，运行时会自动发送 `stream_options.include_usage=true`，以便 OpenAI 兼容接口在流式尾包返回 usage 并维持 token 统计。
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
| `nagaagent_mode_enabled` | `false` | 切换 NagaAgent 提示词和相关 Agent 暴露 |
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
| `cache_max_total_size_mb` | `0` | 附件缓存文件总大小上限（MB）。`0` 表示不按总容量清理；达到上限时优先删除最旧本地缓存副本，有 URL 的记录会保留 UID 与 URL 以便后续回源 |
| `cache_max_records` | `2000` | 附件登记记录最大数量。`0` 表示不限制数量 |
| `cache_max_age_days` | `7` | 附件本地缓存最长保留天数。`0` 表示不按时间清理；有 URL 的记录只删除本地副本并保留 UID/URL，无 URL 的老记录会被删除 |
| `url_reference_max_records` | `2000` | 仅 URL 引用的附件记录最大数量。`0` 表示不限制 |
| `url_max_length` | `8192` | 允许登记的远程附件 URL 最大长度。`0` 表示不限制长度 |

外部接收的远程图片或文件默认会先下载到附件缓存再生成 UID，避免后续 URL 失效；大文件超过阈值时，UID 仍会生成，但绑定的是 URL 引用而不是缓存文件，AI 可在上下文中看到原始 `source_ref`。如果本地缓存因总容量或时间清理被删除，但记录仍保留 URL，后续需要文件内容时会优先按 URL 回源下载。

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
| `prefetch_tools_hide` | `true` | 预取后是否从 tool list 隐藏该工具 |

补充：
- `prefetch_tools` 未配置时默认会注入 `get_current_time`。
- `hot_reload_interval/debounce` 还会用于配置热更新监听器本身。

---

### 4.12 `[search]` 搜索

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `searxng_url` | `""` | SearXNG 地址；为空则禁用搜索包装器 |
| `grok_search_enabled` | `false` | 是否在 `web_agent` 中暴露 `grok_search`；启用后该工具优先于 `web_search` |

补充：
- `searxng_url` 可热更新，运行时会重建搜索客户端。
- `grok_search_enabled` 不需要重建客户端；它只影响 `web_agent` 的工具暴露。

---

### 4.13 `[proxy]` 代理

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `use_proxy` | `true` | 是否允许相关工具使用代理 |
| `http_proxy` | `""` | HTTP 代理地址 |
| `https_proxy` | `""` | HTTPS 代理地址 |

环境变量兜底：
- 若 TOML 未配置 `http_proxy` / `https_proxy`，会尝试 `HTTP_PROXY` / `HTTPS_PROXY`。

说明：
- 该配置会影响走统一 HTTP 请求封装的联网能力，例如 GitHub 仓库自动提取、arXiv 查询及部分第三方 API 请求。
- 当 `use_proxy = false` 时，上述请求不会使用代理，也不会再读取代理环境变量。

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

说明：
- 该配置只影响 `render.py` 的 HTML/Markdown 图片渲染链路，不影响 `crawl_webpage` 等独立浏览器实现。
- 渲染浏览器当前采用单例复用，因此这里限制的是并发页面/上下文数量，而不是浏览器进程数量。
- 配置变更会对后续新的渲染请求生效；已在执行中的渲染任务不受影响。

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
| `send_text_file_max_size_kb` | `512` | 文本文件发送上限（KB） | `<=0` 回退 `512` |
| `send_url_file_max_size_mb` | `100` | URL 文件发送上限（MB） | `<=0` 回退 `100` |

---

### 4.21 `[bilibili]` 自动提取

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
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
- 视频文件下载、清晰度、时长和体积限制仍由本节配置控制；自动提取的转发消息也会通过统一发送层写入历史，供后续 AI 回复读取。

---

### 4.20.1 `[arxiv]` 自动提取

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
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

---

### 4.20.2 `[github]` 仓库自动提取

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `auto_extract_enabled` | `false` | 是否自动提取 GitHub 仓库链接或 `owner/repo` 仓库 ID | |
| `request_timeout_seconds` | `10.0` | GitHub API 请求超时（秒） | `<=0` 回退 `10`，`>60` 截断到 `60` |
| `auto_extract_group_ids` | `[]` | 功能级群白名单 | 空时跟随全局 access |
| `auto_extract_private_ids` | `[]` | 功能级私聊白名单 | 空时跟随全局 access |
| `auto_extract_max_items` | `3` | 单条消息最多自动处理几个仓库 | `<=0` 回退 `3`，`>10` 截断到 `10` |

触发规则：
- 命中 `https://github.com/owner/repo`、`github.com/owner/repo` 或 `git@github.com:owner/repo.git` 时触发。
- 裸 `owner/repo` 会作为 GitHub 仓库 ID 尝试一次 public API 请求；失败时只记录日志，不向会话发送错误消息。
- 仅支持 public 仓库。卡片渲染为图片，包含仓库 ID、作者头像、简介、stars、forks、issues、contributors、watchers、语言、许可证、默认分支和更新时间等信息。
- GitHub API 请求默认复用全局 `[proxy]` 代理设置。

自动提取调度说明：
- 斜杠命令优先级高于自动处理管线；命中命令后直接分发并结束本轮后续处理，不会触发自动提取或 AI 自动回复。命令输入和命令输出会写入历史，供后续 AI 轮次读取。
- 同一条消息内，自动处理管线会并行检测 Bilibili、arXiv、GitHub 等已注册管线。
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

关键行为：
- 默认密码 `changeme` 禁止登录，必须先修改。
- 未配置或为空时，会回退默认密码并标记为“默认密码模式”。
- `webui.url/port/password` 修改需重启 WebUI 进程（机器人主进程中也属于重启生效类）。

---

### 4.24 `[api]` Runtime API / OpenAPI

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `enabled` | `true` | 是否启用主进程 Runtime API |
| `host` | `127.0.0.1` | Runtime API 监听地址 |
| `port` | `8788` | Runtime API 端口（1..65535） |
| `auth_key` | `changeme` | 请求头鉴权密钥（`X-Undefined-API-Key`） |
| `openapi_enabled` | `true` | 是否暴露 `/openapi.json` |

关键行为：
- Runtime API 仅在主进程 `Undefined` 中启动，WebUI 通过后端代理调用。
- WebUI 会自动读取 `config.toml` 的 `api.auth_key` 并转发，不在前端暴露密钥。
- 默认密钥 `changeme` 仅用于初始开发环境，生产请务必替换。

详见 [docs/openapi.md](openapi.md)。

---

### 4.25 `[cognitive]` 认知记忆

### 4.24.1 根配置

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `enabled` | `true` | 开启认知记忆 |
| `bot_name` | `Undefined` | 史官改写中使用的 bot 名称 |

### 4.24.2 `[cognitive.vector_store]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `path` | `data/cognitive/chromadb` | Chroma 存储目录 |
| `scheduler_foreground_burst` | `8` | Chroma 前台连续处理上限；达到后若有维护/后台任务，会让出一次执行机会。需重启 |

### 4.24.3 `[cognitive.query]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `auto_top_k` | `3` | 自动注入召回条数 |
| `auto_scope_candidate_multiplier` | `2` | 自动注入时每个作用域候选扩展倍数（候选数≈`auto_top_k * multiplier`） |
| `auto_current_group_boost` | `1.15` | 群聊自动检索时，当前群命中额外加权系数 |
| `auto_current_private_boost` | `1.25` | 私聊自动检索时，当前私聊命中额外加权系数 |
| `enable_rerank` | `true` | 认知检索是否启用 rerank |
| `recent_end_summaries_inject_k` | `30` | 最近 end 摘要注入条数，`0` 禁用 |
| `time_decay_enabled` | `true` | 是否启用时间衰减加权 |
| `time_decay_half_life_days_auto` | `14.0` | 自动注入场景半衰期 |
| `time_decay_half_life_days_tool` | `60.0` | 工具检索场景半衰期 |
| `time_decay_boost` | `0.2` | 时间加权强度 |
| `time_decay_min_similarity` | `0.35` | 应用时间加权的相似度阈值 |
| `tool_default_top_k` | `12` | 工具调用默认 top-k |
| `profile_top_k` | `8` | 侧写检索 top-k |
| `rerank_candidate_multiplier` | `3` | 候选倍数（`top_k * multiplier`） |

### 4.24.4 `[cognitive.historian]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `rewrite_max_retry` | `2` | 绝对化改写最大重试 |
| `recent_messages_inject_k` | `12` | 注入给史官的近期消息条数 |
| `recent_message_line_max_len` | `240` | 每条近期消息最大字符数 |
| `source_message_max_len` | `800` | 当前触发消息最大字符数 |
| `poll_interval_seconds` | `1.0` | 队列轮询间隔 |
| `stale_job_timeout_seconds` | `300.0` | processing 超时回收阈值 |

### 4.24.5 `[cognitive.profile]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `path` | `data/cognitive/profiles` | 侧写存储目录 |
| `revision_keep` | `5` | 保留历史版本数量 |

### 4.24.6 `[cognitive.queue]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `path` | `data/cognitive/queues` | 队列目录 |
| `failed_max_age_days` | `30` | failed 文件保留天数 |
| `failed_max_files` | `500` | failed 文件上限 |
| `failed_cleanup_interval` | `100` | 处理多少次后触发清理 |
| `job_max_retries` | `3` | 单任务自动重试次数 |

---

### 4.26 `[memes]` 表情包库

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

### 4.27 `[naga]` Naga 外部网关集成

> **⚠️ 此功能面向与 NagaAgent 对接的高级场景，普通用户不建议开启。**

启用后允许 NagaAgent 通过绑定审批机制向 QQ 群/用户发送回调消息。共享密钥统一使用 `Authorization: Bearer {naga.api_key}`，其中 `messages/send` 与 `unbind` 还会额外校验 `bind_uuid + naga_id + delivery_signature`。

**开关分层**：

| 开关 | 控制范围 | 默认值 |
|------|---------|--------|
| `[features].nagaagent_mode_enabled` | 总开关：AI 侧行为（提示词切换、工具暴露） | `false` |
| `[naga].enabled` | 子开关：外部网关集成（回调 API、`/naga` 命令、绑定管理） | `false` |

- 仅当 `[api].enabled = true`、`[features].nagaagent_mode_enabled = true`、`[naga].enabled = true` 三者同时成立时，外部网关集成才会生效（API 端点注册、`/naga` 命令可用）
- 若只需 NagaAgent 解答能力而不需要外部回调联动，可只开启 `nagaagent_mode_enabled`
- `nagaagent_mode_enabled = false` 时强制关闭所有 Naga 功能，无论 `naga.enabled` 值

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `enabled` | `false` | 是否启用外部网关集成 | 需同时开启 `nagaagent_mode_enabled` |
| `api_url` | `""` | Naga 服务器 API 地址 | 为空时无法向远端提交 bind request / revoke 同步 |
| `api_key` | `""` | Undefined ↔ Naga 共享密钥 | 回调端点通过 `Authorization: Bearer` 校验 |
| `moderation_enabled` | `true` | 是否启用 Naga 外发消息审核 | 关闭后 `messages/send` 直接跳过审核，返回 `moderation.status=skipped_disabled` |
| `allowed_groups` | `[]` | Naga 服务群聊名单 | 绑定命令和回调群发仅限名单内的群 |

**作用域规则**：
- 群聊场景下，所有 `/naga` 子命令仅在 `allowed_groups` 内的群可用
- 私聊场景不受 `allowed_groups` 限制
- 回调群发仅发到绑定时的群（该群须仍在 `allowed_groups` 内）
- 回调私聊只需开关开启，不受 `allowed_groups` 限制
- `/api/v1/naga/*` 端点仅在 `api.enabled`、`nagaagent_mode_enabled`、`naga.enabled` 三者均开启时注册
- Runtime API 关闭时，`/naga` 命令也不会在 `/help` 中显示

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
- `api.*`（`enabled/host/port/auth_key/openapi_enabled`）
- `memes.blob_dir`
- `memes.preview_dir`
- `memes.db_path`
- `memes.vector_store_path`
- `memes.queue_path`
- `naga.*`（`enabled/api_url/api_key/moderation_enabled/allowed_groups`）

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
- `search.searxng_url`（搜索客户端刷新）
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

#### `api_endpoints`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `api_endpoints.jkyai_base_url` | `JKYAI_BASE_URL` |
| `api_endpoints.xxapi_base_url` | `XXAPI_BASE_URL` |

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

#### `history`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `history.max_records` | `HISTORY_MAX_RECORDS` |

#### `image_gen`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `image_gen.provider` | `IMAGE_GEN_PROVIDER` |

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
| `models.agent.model_name` | `AGENT_MODEL_NAME` |
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
| `models.chat.reasoning_content_replay` | `CHAT_MODEL_REASONING_CONTENT_REPLAY` |
| `models.chat.responses_force_stateless_replay` | `CHAT_MODEL_RESPONSES_FORCE_STATELESS_REPLAY` |
| `models.chat.responses_tool_choice_compat` | `CHAT_MODEL_RESPONSES_TOOL_CHOICE_COMPAT` |
| `models.chat.system_prompt_as_user` | `CHAT_MODEL_SYSTEM_PROMPT_AS_USER` |

#### `models.embedding`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `models.embedding.context_window_tokens` | `EMBEDDING_MODEL_CONTEXT_WINDOW_TOKENS` |

#### `models.grok`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `models.grok.api_key` | `GROK_MODEL_API_KEY` |
| `models.grok.api_url` | `GROK_MODEL_API_URL` |
| `models.grok.context_window_tokens` | `GROK_MODEL_CONTEXT_WINDOW_TOKENS` |
| `models.grok.max_tokens` | `GROK_MODEL_MAX_TOKENS` |
| `models.grok.model_name` | `GROK_MODEL_NAME` |

#### `models.naga`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `models.naga.api_key` | `NAGA_MODEL_API_KEY` |
| `models.naga.api_mode` | `NAGA_MODEL_API_MODE` |
| `models.naga.api_url` | `NAGA_MODEL_API_URL` |
| `models.naga.context_window_tokens` | `NAGA_MODEL_CONTEXT_WINDOW_TOKENS` |
| `models.naga.model_name` | `NAGA_MODEL_NAME` |
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

#### `models.security`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `models.security.api_key` | `SECURITY_MODEL_API_KEY` |
| `models.security.api_mode` | `SECURITY_MODEL_API_MODE` |
| `models.security.api_url` | `SECURITY_MODEL_API_URL` |
| `models.security.context_window_tokens` | `SECURITY_MODEL_CONTEXT_WINDOW_TOKENS` |
| `models.security.model_name` | `SECURITY_MODEL_NAME` |
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
| `models.vision.model_name` | `VISION_MODEL_NAME` |
| `models.vision.reasoning_content_replay` | `VISION_MODEL_REASONING_CONTENT_REPLAY` |
| `models.vision.responses_force_stateless_replay` | `VISION_MODEL_RESPONSES_FORCE_STATELESS_REPLAY` |
| `models.vision.responses_tool_choice_compat` | `VISION_MODEL_RESPONSES_TOOL_CHOICE_COMPAT` |
| `models.vision.system_prompt_as_user` | `VISION_MODEL_SYSTEM_PROMPT_AS_USER` |

#### `onebot`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `onebot.token` | `ONEBOT_TOKEN` |
| `onebot.ws_url` | `ONEBOT_WS_URL` |

#### `proxy`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `proxy.use_proxy` | `USE_PROXY` |

#### `search`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `search.searxng_url` | `SEARXNG_URL` |

#### `skills`

| TOML 路径 | 环境变量 |
|-----------|----------|
| `skills.hot_reload` | `SKILLS_HOT_RELOAD` |
| `skills.intro_hash_path` | `AGENT_INTRO_HASH_PATH` |
| `skills.prefetch_tools_hide` | `PREFETCH_TOOLS_HIDE` |

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
