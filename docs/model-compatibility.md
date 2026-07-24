# 模型 API 与兼容层

本文集中说明 Undefined 如何适配不同模型 SDK、API Mode、CoT / reasoning 载体、多轮工具调用，以及模型把工具调用错误写入普通文本时的后备解析。配置字段及默认值仍以[配置与热更新说明](configuration.md#44-models-模型配置总览)为准。

## 处理链路与职责边界

主 Chat 请求依次经过以下层次：

```text
模型配置
  → ModelRequester / 请求体构建
  → OpenAI 或 Anthropic SDK
  → Transport 响应归一化
  → AIClient ask_loop
  → 原生或恢复出的 tool_calls
  → ToolManager 执行与历史回写
```

- `src/Undefined/ai/llm/` 负责 SDK 客户端、请求参数、流式聚合、出站消息清洗和 thinking 提取。
- `src/Undefined/ai/transports/` 负责 Chat Completions、Responses 与 Anthropic Messages 的请求结构转换、响应归一化及推理载体回放。
- `src/Undefined/ai/client/ask_loop.py` 负责主 Chat 多轮决策、工具可见性校验、工具执行和缺少工具调用时的纠正重试。
- `src/Undefined/utils/tool_calls.py` 只负责严格解析受支持的文本工具封包，不直接执行工具。

所有模式最终都会归一化为主循环可消费的 `choices[].message` 结构。服务商原生的工具调用、推理载体和传输状态会尽可能保留，避免为每个 SDK 建立独立业务执行链。

## SDK 与 API Mode

| `api_mode` | SDK 入口 | 主要适配 |
|---|---|---|
| `openai.chat_completions` | `AsyncOpenAI.chat.completions.create(...)` | 使用 `messages` / `tool_calls`；兼容 `reasoning_content`、`reasoning_details`、`reasoning`、`encrypted_content` 和 `thinking` 等推理字段 |
| `openai.responses` | `AsyncOpenAI.responses.create(...)` | 在 `input`、`instructions`、`function_call`、`function_call_output` 与内部消息之间转换；支持 `previous_response_id` 增量续轮和 stateless replay |
| `anthropic.messages` | `AsyncAnthropic.messages.create(...)` / `messages.stream(...)` | 转换顶层 `system`、图片、`tool_use` / `tool_result`、`thinking` / `redacted_thinking` blocks，并校验 Anthropic 的 token 与 thinking 约束 |

共同规则：

- OpenAI 模式的 `max_tokens <= 0` 会省略输出上限；Anthropic Messages 要求 `max_tokens` 为正整数。
- `thinking_param_enabled` 只控制由 `thinking_enabled` 自动生成的顶层 `thinking`，不会关闭 `reasoning_effort`，也不会覆盖调用方显式传入的 `thinking`。
- `reasoning_enabled` 与 `reasoning_effort` 按当前 API Mode 映射：Chat 使用顶层 `reasoning_effort`，Responses 合并到 `reasoning.effort`，Anthropic 使用 `output_config.effort`。
- `system_prompt_as_user` 只作用于 Chat Completions；它会把 `system` / `developer` 内容合并到首条 `user`，用于兼容不接受系统角色的服务。
- Responses 默认使用官方对象型 `tool_choice`。仅当兼容网关明确不支持时，才启用 `responses_tool_choice_compat` 降级为字符串 `"required"`。
- Responses 默认使用 `previous_response_id + function_call_output` 增量续轮；`responses_force_stateless_replay` 会强制回放完整历史。检测到上游缺失前序工具调用状态时，运行时也可自动降级到 stateless replay。
- 启用流式请求时，三种模式分别使用对应 SDK 的流式接口并聚合为统一响应；只有明确的流式参数不兼容或 SDK 未实现才回退非流式请求。
- OpenAI 模式可以生成按模型、调用类型和会话作用域稳定隔离的 `prompt_cache_key`；Anthropic 不发送该字段，其缓存扩展通过 `request_params.cache_control` 配置。

精确字段、默认值和 `request_params` 保留字段规则见[生成模型通用字段](configuration.md#441-生成模型通用字段)。

## CoT 与推理载体续传

Undefined 将“是否请求模型思考”和“是否在下一轮回放已有推理载体”拆成独立能力：

| 配置 | 作用 |
|---|---|
| `thinking_enabled` / `thinking_param_enabled` | 控制是否自动构建旧式或服务商兼容的 `thinking` 请求参数 |
| `reasoning_enabled` / `reasoning_effort` | 控制当前 API Mode 的 effort 参数，不受 `thinking_param_enabled` 影响 |
| `thinking_include_budget` / `thinking_budget_tokens` | 控制手动 thinking 预算；Anthropic adaptive thinking 不发送手动预算 |
| `thinking_tool_call_compat` | 在本地历史保留兼容的可读 `reasoning_content`，用于日志与旧历史回退 |
| `reasoning_content_replay` | 向上游续传原生推理结构；关闭后过滤明文、summary、签名、密文和 redacted thinking 载体 |

各传输模式保留的原生载体不同：

- Chat Completions 优先回放原始 `reasoning_content`、`reasoning_details`、`reasoning`、`encrypted_content` 或 `thinking` 字段；旧历史没有原始载体时才使用可读 `reasoning_content`。
- Responses 按原顺序回放 reasoning output items，并在需要时请求及回放 `reasoning.encrypted_content`。stateless replay 会同时回放有效的 message、function call、function output 和 reasoning items。
- Anthropic Messages 按原顺序回放 `thinking`、`redacted_thinking`、`text` 与 `tool_use` blocks；关闭推理回放时只过滤 thinking 类 block，不破坏工具调用结构。

若上游返回 `400 Validation: Unsupported parameter(s): thinking`，应对该模型关闭 `thinking_param_enabled`；这不会影响 `reasoning_effort`。更完整的迁移说明见[配置文档中的思维链续传说明](configuration.md#思维链续传迁移说明)。

## 文本 Tool Call 后备解析

部分模型或兼容网关偶尔不返回结构化 `tool_calls`，而是把调用序列化到普通 `assistant.content`。主 Chat 循环会识别以下严格限定的完整文本封包，将其转换为原生 `tool_calls` 后交回同一执行链。

该机制与 API Mode、CoT 和多模型池开关相互独立。它目前只作用于主 Chat 循环，子 Agent 仍要求服务商返回原生结构化工具调用。

### 连续 JSON 对象

兼容 `tool` 字段形式：

```text
{"tool":"send_message","arguments":{"message":"在做了"}}
{"tool":"end","arguments":{"memo":"已回应","observations":[]}}
```

也兼容原生函数字段名形式：

```text
{"name":"music.search_songs","arguments":{"query":"君往何处 m2u","limit":5}}
{"name":"end","arguments":{"memo":"搜索 m2u 的《君往何处》","observations":[]}}
```

JSON 对象可以单独出现，也可以由空白分隔后连续出现；`tool` 与 `name` 两种封包允许混排。`arguments` 可以是对象或编码该对象的 JSON 字符串；`name` 形式要求显式提供 `arguments`，避免把普通的名称 JSON 误判为工具调用。

### `tool` 标签

```text
<tool name="end" parameters="{\"memo\":\"静默处理\",\"observations\":[]}"></tool>

<tool name="send_message" params='{"message":"在做了在做了"}' />
<tool name="end" params='{"memo":"已回应","observations":[]}' />
```

标签支持空的成对形式或自闭合形式；参数属性名可以是 `params`、`parameters` 或 `arguments`。完整封包外层允许使用 Markdown 代码围栏。

### `tool_execution` / `tool_call` 标签

```text
<tool_execution>
<tool_call name="music-_-search_songs" arguments='{"query":"克罗地亚狂想曲 Maksim","limit":10}'>
</tool_call>
</tool_execution>
```

`tool_execution` 外层可以包含一个或多个 `tool_call`。`tool_call` 支持空的成对标签或自闭合标签，`name` 必填，`arguments` 缺省为 `{}`。工具名使用模型实际看到的 API 名称，后续仍由现有映射还原为内部名称。

### `function_calls` / `invoke` / `arguments` 标签

```text
<function_calls>
<invoke name="music.search_songs">
<arguments>
{"query":"童话镇 暗杠","limit":5}
</arguments>
</invoke>
</function_calls>
```

`function_calls` 外层可以包含一个或多个 `invoke`。每个 `invoke` 只接受必填的 `name` 属性和一个 `arguments` 子标签；`arguments` 内容必须是 JSON 对象。多个调用按原顺序转换到同一个原生 `tool_calls` 列表。

### 转换与执行边界

- 服务商原生返回的结构化 `tool_calls` 始终优先，不与文本恢复结果合并。
- 文本必须完全由一种受支持的封包结构组成；封包前后或调用之间不能夹带普通说明文字。
- 每个恢复出的调用都会获得独立调用 ID，并沿用现有工具名映射、参数解析、权限检查、生命周期事件和执行路径。
- 普通工具继续按现有规则并发执行；`end` 与其他工具同轮出现时会拒绝本轮 `end`，等待其他结果回填后由模型下一轮决定是否结束。
- 成功转换后，原始文本封包不会写回对话上下文；系统会保存标准的 `assistant.tool_calls` 以及对应的 `role=tool` 结果。
- 即使恢复出的工具当前不可用，也会以原生调用与拒绝结果写入历史，模型可以在下一轮重新决策。
- Responses 模式恢复出文本工具调用后，下一轮强制使用 stateless replay，避免合成调用 ID 与上游响应状态不一致。

### Tool Search 与权限边界

文本恢复不能绕过当前请求的工具投影。每个工具名都必须属于会话权限过滤后、该轮实际暴露给模型的 schema；尚未加载的延迟工具必须先调用 `tool_search`，并等待下一轮获得 schema 后才能执行。加载生命周期与查询规则见 [Tool Search 按需工具加载](tool-search.md)。

### 无法解析时的重试、回退与日志

检测到疑似工具封包但无法安全解析时，系统不会执行其中的任何调用，而是沿用普通“未调用工具”纠正流程：

1. 将该轮原始 `assistant.content` 保留在上下文中。
2. 追加通用纠正提示，并发起下一轮模型请求。
3. 达到 `[core].missing_tool_call_retries` 上限后，按普通文本 fallback 原样返回或通过当前发送回调发送。

成功恢复时，`[工具调用兼容]` 日志只记录调用数量和工具名，不记录完整参数正文。解析失败时，该日志记录失败原因和内容长度；若随后进入纠正重试，`[AI回复未调用工具]` warning 会以 `raw_content=repr(...)` 完整记录该轮原始响应。达到重试上限且不再进入下一轮时，不会额外输出“即将进入下一轮重试”日志。

这些格式仅是服务端容错规则，不会写入系统提示、工具描述或缺少工具调用时的纠正提示。由于纠正重试日志包含完整模型响应，部署时应按对话数据的敏感级别保护并轮转日志文件。

## 常见兼容问题

| 现象 | 优先检查 |
|---|---|
| `Unsupported parameter(s): thinking` | 对该模型设置 `thinking_param_enabled=false`；不要关闭仍需使用的 effort |
| Responses 网关因对象型 `tool_choice` 返回 500 | 确认网关不兼容后再尝试 `responses_tool_choice_compat=true` |
| Responses 续轮报告找不到前序 tool call | 尝试 `responses_force_stateless_replay=true`，并检查上游是否完整保留 `previous_response_id` 状态 |
| 模型只返回文本工具封包 | 确认格式属于本页支持范围、正文没有混入普通文本，且工具已在当前轮暴露 |
| 工具恢复成功但被拒绝执行 | 检查会话权限和 Tool Search 加载轮次；文本回退不能绕过 schema 可见性 |

相关文档：

- [配置与热更新说明](configuration.md)
- [Tool Search 按需工具加载](tool-search.md)
- [多模型池功能](multi-model.md)
- [Undefined 详细架构图](../ARCHITECTURE.md)
