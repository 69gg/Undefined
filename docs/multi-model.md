# 多模型池功能

## 功能概述

- **Chat 模型池（私聊）**：轮询/随机自动切换，或在私聊中通过「选X」指定模型
- **Agent 模型池**：按策略（轮询/随机）自动分配，无需用户干预

> 仅私聊支持用户手动切换 Chat 模型；群聊始终使用主模型。

## 配置方式

### 方式一：WebUI

启动 `uv run Undefined-webui`，登录后进入「配置修改」页：

- **全局开关**：`features` → `pool_enabled` 设为 `true`
- **Chat 模型池**：`models` → `chat` → `pool`，设置 `enabled`、`strategy`，在 `models` 列表中添加/移除条目
- **Agent 模型池**：`models` → `agent` → `pool`，同上

每次修改自动保存并热更新，无需重启。

### 方式二：直接编辑 config.toml

## 配置

### 1. 全局开关

```toml
[features]
pool_enabled = true  # 默认 false，需显式开启
```

### 2. Chat 模型池

```toml
[models.chat.pool]
enabled = true
strategy = "round_robin"  # "default" | "round_robin" | "random"

[[models.chat.pool.models]]
model_name = "claude-sonnet-4-20250514"
api_url = "https://api.anthropic.com/v1"
api_key = "sk-ant-xxx"
api_mode = "anthropic.messages"
thinking_param_enabled = true
thinking_enabled = true
thinking_include_budget = false  # adaptive thinking
reasoning_content_replay = true
# 其他字段（max_tokens、thinking_param_enabled、reasoning_*、stream_enabled 等）可选，缺省继承主模型
# Anthropic Messages 要求 max_tokens 为正整数

[[models.chat.pool.models]]
model_name = "deepseek-chat"
api_url = "https://api.deepseek.com/v1"
api_key = "sk-ds-xxx"
api_mode = "openai.chat_completions"
```

### 3. Agent 模型池

```toml
[models.agent.pool]
enabled = true
strategy = "round_robin"  # "default" | "round_robin" | "random"

[[models.agent.pool.models]]
model_name = "claude-sonnet-4-20250514"
api_url = "https://api.anthropic.com/v1"
api_key = "sk-ant-xxx"
api_mode = "anthropic.messages"
reasoning_content_replay = true
```

`thinking_param_enabled` 默认 `true`。将某个池条目设为 `false` 只会禁止该条目根据 `thinking_enabled` 自动发送顶层 `thinking`，不会关闭 `reasoning_effort`，也不会覆盖调用方显式提供的 `thinking`。

### strategy 说明

| 值 | 行为 |
|----|------|
| `default` | 只使用主模型，忽略池中模型 |
| `round_robin` | 按顺序轮流使用池中模型 |
| `random` | 每次随机选择池中模型 |

> `pool.models` 中只有 `model_name` 必填，其余字段缺省时继承主模型配置。每个条目均可独立设置 `api_mode`、完整 `thinking_*` / `reasoning_*`、`reasoning_content_replay`、Responses 兼容开关、`stream_enabled` 与 `request_params`。

`max_tokens` 也会按条目独立继承或覆盖。OpenAI 模式下，显式设为 `0` 或负数会保留该值，并在实际请求中省略 token 上限字段；Anthropic Messages 要求为正整数，非正数会在请求发出前报错。

## 文本工具封包兼容回退（仅服务端）

部分 OpenAI 兼容模型偶尔不会返回结构化 `tool_calls`，而是把工具调用写进普通 `content`。主 Chat 循环会在响应侧兼容以下完整文本格式：

```text
{"tool":"end","arguments":{"memo":"静默处理","observations":[]}}
{"tool":"send_message","arguments":{"message":"在做了"}}
{"tool":"end","arguments":{"memo":"已回应","observations":[]}}
```

也兼容使用原生函数字段名的连续 JSON：

```text
{"name":"music.search_songs","arguments":{"query":"君往何处 m2u","limit":5}}
{"name":"end","arguments":{"memo":"搜索 m2u 的《君往何处》","observations":[]}}
```

JSON 对象可以单独出现，也可以由空白分隔后连续出现；`tool` 与 `name` 两种封包允许混排。`arguments` 可以是对象或编码该对象的 JSON 字符串；`name` 形式要求显式提供 `arguments`，以免把普通的名称 JSON 误判为工具调用。连续调用会转换为同一个原生 `tool_calls` 列表，其中普通工具沿用现有并发执行；`end` 与其他工具同轮出现时仍拒绝本轮 `end`，等待其他工具结果回填后由模型下一轮决定是否结束。

```text
<tool name="end" parameters="{\"memo\":\"静默处理\",\"observations\":[]}"></tool>

<tool name="send_message" params='{"message":"在做了在做了"}' />
<tool name="end" params='{"memo":"已回应","observations":[]}' />
```

标签格式支持空的成对标签或自闭合标签；参数属性名可以是 `params`、`parameters` 或 `arguments`。完整封包外层允许使用 Markdown 代码围栏。

```text
<tool_execution>
<tool_call name="music-_-search_songs" arguments='{"query":"克罗地亚狂想曲 Maksim","limit":10}'>
</tool_call>
</tool_execution>
```

`tool_execution` 外层可以包含一个或多个 `tool_call`；`tool_call` 支持空的成对标签或自闭合标签，`name` 必填，`arguments` 缺省为 `{}`。工具名使用模型实际看到的 API 名称，后续仍由现有映射还原为内部名称。

这是一项服务端兼容措施，不是模型输出契约，也不会写入系统提示、工具描述或缺少工具调用时的纠错提示。处理边界如下：

- 服务商原生返回的结构化 `tool_calls` 始终优先，不与文本回退结果合并。
- 文本必须完全由受支持的工具封包组成。检测到封包标记但存在额外说明、格式错误或非对象参数时，按普通“未调用工具”响应进入原有重试流程；重试耗尽后按普通文本 fallback 原样发送。
- 每个工具名必须属于当前会话经过权限过滤且在本轮实际暴露的 schema；文本回退不能绕过 Tool Search 加载阶段。
- 成功转换后的文本不会以原始封包写回上下文，而是保存为原生 `assistant.tool_calls`；即使工具本轮未暴露，也会配对写入原生 `role=tool` 拒绝结果，供下一轮模型继续决策。
- 转换后的调用继续使用原有名称映射、工具生命周期事件、并发执行和 `end` 同轮拒绝规则，不建立第二套执行路径。
- Responses 模式恢复出文本工具调用后，下一轮强制使用 stateless replay，避免合成调用 ID 与上游响应状态不一致。
- 运行日志使用 `[工具调用兼容]` 标记恢复或解析失败原因，不记录完整参数正文。

## 私聊使用方法

### 自动轮换

配置 `strategy = "round_robin"` 或 `"random"` 后，私聊请求会自动在池中模型间切换，无需任何操作。

### 手动指定模型（私聊）

1. 私聊发送 `/compare <问题>` 或 `/pk <问题>`，bot 并发请求所有模型并编号返回：

```
你: /compare 写一首关于春天的诗

bot:
正在向 3 个模型发送问题，请稍候...

问题: 写一首关于春天的诗

【1】gpt-4o
春风拂面暖如酥...

【2】claude-sonnet-4-20250514
春日融融暖意浓...

【3】deepseek-chat
春回大地万象新...

回复「选X」可切换到该模型并继续对话
```

2. 5 分钟内回复 `选2`，后续私聊固定使用第 2 个模型继续对话。

3. 偏好持久化保存在 `data/model_preferences.json`，重启后保留。

## 开关层级

```
features.pool_enabled        ← 全局总开关（false 时完全不生效）
  └─ models.chat.pool.enabled   ← Chat 模型池开关
  └─ models.agent.pool.enabled  ← Agent 模型池开关
```

## 注意事项

- 不同模型使用独立队列，互不影响
- 所有模型的 Token 使用均会被统计
- 「选X」状态 5 分钟后过期
- 群聊不受多模型池影响，始终使用主模型

## 代码结构

| 文件 | 职责 |
|------|------|
| `config/models.py` | `ModelPool`, `ModelPoolEntry` 数据类 |
| `config/loader.py` | 解析 pool 配置，字段缺省继承主模型 |
| `ai/model_selector.py` | 纯选择逻辑：策略、偏好存储、compare 状态 |
| `services/model_pool.py` | 私聊交互服务：`/compare`、「选X」、`select_chat_config` |
| `services/coordinator/` | 持有 `ModelPoolService`，私聊队列投递时选模型 |
| `handlers.py` | 私聊消息委托给 `model_pool.handle_private_message()` |
| `skills/agents/runner.py` | Agent 执行时调用 `model_selector.select_agent_config()` |
| `utils/queue_intervals.py` | 注册 pool 模型的队列间隔 |
