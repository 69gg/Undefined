# Runtime API / OpenAPI 指南

本文档说明 Undefined 主进程暴露的 Runtime API（含 OpenAPI 文档），以及 WebUI / App 如何通过 Management API 代理安全调用。

> 职责边界：
>
> - **Management API**：配置、日志、Bot 启停、bootstrap probe、远程管理入口
> - **Runtime API**：主进程运行态能力（探针、记忆、认知、AI Chat、表情包库）
>
> 如果你想看控制面接口，请同时参考 [Management API 文档](management-api.md)。

## 1. 配置项

在 `config.toml` 中使用 `[api]`：

```toml
[api]
enabled = true
host = "127.0.0.1"
port = 8788
auth_key = "changeme"
openapi_enabled = true

# 工具调用 API
tool_invoke_enabled = false
tool_invoke_expose = "tools+toolsets"
tool_invoke_allowlist = []
tool_invoke_denylist = []
tool_invoke_timeout = 120
tool_invoke_callback_timeout = 10
```

- `enabled`：是否启动 Runtime API。
- `host` / `port`：监听地址和端口。
- `auth_key`：API 鉴权密钥（请求头 `X-Undefined-API-Key`）。
- `openapi_enabled`：是否开放 `/openapi.json`。
- `tool_invoke_enabled`：是否启用工具调用 API（默认关闭，需显式开启）。
- `tool_invoke_expose`：暴露的工具范围（`tools` / `toolsets` / `tools+toolsets` / `agents` / `all`）。
- `tool_invoke_allowlist`：工具白名单（非空时覆盖 `expose` 规则）。
- `tool_invoke_denylist`：工具黑名单（始终优先）。
- `tool_invoke_timeout`：单次调用超时（秒）。
- `tool_invoke_callback_timeout`：回调请求超时（秒）。

默认值：

- `enabled = true`
- `host = 127.0.0.1`
- `port = 8788`
- `auth_key = changeme`
- `openapi_enabled = true`
- `tool_invoke_enabled = false`
- `tool_invoke_expose = tools+toolsets`
- `tool_invoke_allowlist = []`
- `tool_invoke_denylist = []`
- `tool_invoke_timeout = 120`
- `tool_invoke_callback_timeout = 10`

建议第一时间修改 `auth_key`，不要在公网直接暴露该端口。

## 2. 鉴权规则

- 除 `/api/v1/naga/*` 外，所有 `/api/*` 路由都要求请求头：

```http
X-Undefined-API-Key: <your_key>
```

- `health` 与 `openapi.json` 不要求该 Header（仅用于探活与文档发现）。

## 3. OpenAPI 文档

- 文档地址：`GET /openapi.json`
- 若 `openapi_enabled = false`，返回 `404`。

示例：

```bash
curl http://127.0.0.1:8788/openapi.json
```

## 4. 主要接口

### 健康检查

- `GET /health`

返回运行状态、版本和时间戳。

### 探针

- `GET /api/v1/probes/internal`：进程内部探针。
- `GET /api/v1/probes/external`：外部依赖探测。

#### 内部探针响应字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `timestamp` | `string` | ISO 时间戳 |
| `version` | `string` | Undefined 版本号 |
| `python` | `string` | Python 版本（如 `3.12.4`） |
| `platform` | `string` | 操作系统（如 `Linux`） |
| `uptime_seconds` | `float` | 进程运行时长（秒） |
| `onebot` | `object` | OneBot 连接状态（`connected`、`running`、`ws_url` 等） |
| `queues` | `object` | 请求队列快照（`processor_count`、`inflight_count`、`totals` 按优先级分布；lane 包含 `superadmin`、`group_superadmin`、`private`、`group_mention`、`group_normal`、`background`，`retry` 表示各 lane 中待执行的 LLM 重试请求数） |
| `message_batcher` | `object` | 消息合并器快照（`config` 含 `enabled`/`window_seconds`/`pre_send_seconds`/`speculative_enabled`/`strategy`/`max_window_seconds`/`max_messages_per_batch`/`group_enabled`/`private_enabled`/`allow_cancel_after_send`/`shutdown`；`pending_buckets` 当前缓冲桶数；`buckets[]` 列出每个桶的 `scope`/`sender_id`/`count`/`elapsed_seconds`/`phase`（`typing`/`speculating`/`finalizing`）/`has_inflight`/`has_speculative_dispatch`） |
| `memory` | `object` | 长期记忆（`count`：条数） |
| `cognitive` | `object` | 认知服务（`enabled`、`queue`） |
| `api` | `object` | Runtime API 配置（`enabled`、`host`、`port`、`openapi_enabled`） |
| `skills` | `object` | 技能统计，包含 `tools`、`toolsets`、`agents`、`pipelines`、`commands`、`anthropic_skills` 子对象 |
| `models` | `object` | 模型配置；聊天类模型包含 `model_name`、脱敏 `api_url`、`api_mode`、`thinking_enabled`、`thinking_tool_call_compat`、`reasoning_content_replay`、`system_prompt_as_user`、`responses_tool_choice_compat`、`responses_force_stateless_replay`、`prompt_cache_enabled`、`reasoning_enabled`、`reasoning_effort` |

`skills` 下各分类均提供轻量摘要：`tools` 是当前可调用工具总表，`toolsets` 单独拆出 `skills/toolsets/` 下的工具集工具，`agents` 对应 `skills/agents/`，`pipelines` 对应 `skills/pipelines/`，`commands` 对应 `skills/commands/`，`anthropic_skills` 对应全局 Anthropic Skills。常规注册表子对象结构：

```json
{
  "count": 12,
  "loaded": 12,
  "items": [
    { "name": "get_time", "loaded": true, "calls": 5, "success": 5, "failure": 0 }
  ]
}
```

`toolsets` 额外包含 `categories[]`，用于按工具集类别汇总；`commands` 额外包含 `aliases` 与 `subcommands` 总数；`pipelines` 额外包含 `hot_reload`，用于观察管线热重载 watcher 是否正在运行。

`models` 子对象结构（URL 经脱敏处理，仅保留 scheme + host；embedding/rerank 仅返回 `model_name` 与 `api_url`）：

```json
{
  "chat_model": {
    "model_name": "claude-sonnet-4-20250514",
    "api_url": "https://api.example.com/...",
    "api_mode": "responses",
    "thinking_enabled": false,
    "thinking_tool_call_compat": true,
    "reasoning_content_replay": false,
    "system_prompt_as_user": false,
    "responses_tool_choice_compat": false,
    "responses_force_stateless_replay": false,
    "reasoning_enabled": true,
    "reasoning_effort": "high"
  },
  "embedding_model": { "model_name": "text-embedding-3-small", "api_url": "https://api.example.com/..." }
}
```

说明：`responses_tool_choice_compat` 与 `responses_force_stateless_replay` 通常都保持 `false`；仅建议在 `responses` 请求默认配置下仍返回 `500`，且怀疑上游不兼容状态续轮时再尝试开启。当前已知 `new-api v0.11.4-alpha.3` 存在该兼容问题。

#### 外部探针响应字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `ok` | `bool` | 是否所有探针结果都返回 `status=ok` |
| `timestamp` | `string` | ISO 时间戳 |
| `results` | `array` | 各端点检测结果列表 |

单个检测结果：

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | `string` | 端点名称（如 `chat_model`、`onebot_ws`） |
| `status` | `string` | `ok` / `error` / `skipped` |
| `model_name` | `string` | 关联的模型名称（HTTP 端点） |
| `url` | `string` | 脱敏后的探测 URL（HTTP 端点） |
| `http_status` | `int` | HTTP 响应状态码（仅 `ok` 时） |
| `latency_ms` | `float` | 响应延迟（毫秒，仅 `ok` 时） |
| `error` | `string` | 错误信息（仅 `error` 时） |
| `reason` | `string` | 跳过原因（仅 `skipped` 时，例如 `empty_url`） |
| `host` / `port` | `string` / `int` | WebSocket 端点的主机与端口 |

说明：这里的 HTTP 探针是“可达性/连通性探测”。只要拿到 HTTP 响应就会记为 `status=ok`，真实业务状态应结合 `http_status` 一起解读。
当 Naga 集成未启用时，`naga_model` 会以 `status=skipped`、`reason=naga_integration_disabled` 出现在结果中。

### 记忆（只读）

- `GET /api/v1/memory`
- 查询参数：
  - `q`：关键字过滤（可选）
  - `top_k`：返回条数上限（可选，正整数）
  - `time_from` / `time_to`：ISO 时间范围过滤（可选）

说明：仅提供查看/查询，不提供写入接口，不改变现有记忆存储格式。

### 表情包库

- `GET /api/v1/memes`
  - 查询参数：
    - `q`：通用查询词或列表关键词过滤（可选）
    - `query_mode`：`keyword` / `semantic` / `hybrid`
    - `keyword_query`：单独的关键词查询词（可选）
    - `semantic_query`：单独的语义查询词（可选）
    - `top_k`：检索候选数；带查询词时优先用于检索
    - `enabled`：`true/false`（可选）
    - `animated`：`true/false`（可选）
    - `pinned`：`true/false`（可选）
    - `sort`：`updated_at` / `use_count` / `created_at`
    - `page` / `page_size`
- `GET /api/v1/memes/stats`
- `GET /api/v1/memes/{uid}`
- `GET /api/v1/memes/{uid}/blob`
- `GET /api/v1/memes/{uid}/preview`
- `PATCH /api/v1/memes/{uid}`
- `DELETE /api/v1/memes/{uid}`
- `POST /api/v1/memes/{uid}/reanalyze`
- `POST /api/v1/memes/{uid}/reindex`

说明：
- 表情包库条目使用统一图片 `uid`，与普通图片 `<attachment uid="..."/>` 语义一致。
- 入库文本和向量索引只使用纯文本 `description + tags + aliases`，不依赖 OCR。
- 后台重跑分析使用两阶段 LLM 管线：先判定，再描述。

### 认知记忆检索 / 侧写

- `GET /api/v1/cognitive/events?q=...`
  - 额外支持：`target_user_id`、`target_group_id`、`sender_id`、`request_type`、`top_k`、`time_from`、`time_to`
- `GET /api/v1/cognitive/profiles?q=...`
  - 额外支持：`entity_type`、`top_k`
- `GET /api/v1/cognitive/profile/{entity_type}/{entity_id}`

说明：这些接口仅在 `cognitive.enabled = true` 时可用，否则返回错误。

### WebUI AI Chat（特殊私聊）

- `POST /api/v1/chat`
- Body：

```json
{
  "message": "你好",
  "stream": false
}
```

- `stream = false` 保持同步响应。
- 当 `stream = true` 时，Runtime 会创建 WebChat job。旧接口仍可返回 SSE，但 WebUI 默认使用 job 查询接口续接事件。
- WebChat job 事件格式：
  - `meta`：会话元信息。
  - `stage`：顶层 AI 当前处理阶段，用于 WebUI 在 `AI` 标签后实时显示状态和总已用时；payload 形如 `{"job_id":"...","stage":"waiting_model","elapsed_ms":1234,"detail":"..."}`。阶段和计时由 Runtime job 统一计算，客户端只展示 payload。
  - `agent_stage`：某个 Agent 内部当前阶段，payload 包含 `webchat_call_id`、`stage`、`stage_elapsed_ms`、`elapsed_ms`、`agent_name`。运行中查询可能返回 `transient=true` 的当前快照；这类快照不写入历史。WebUI 将 Agent 阶段作为对应 Agent 摘要行的当前状态展示，不额外渲染为 timeline 小条。
  - `tool_start` / `tool_end`：工具开始与结束。
  - `agent_start` / `agent_end`：Agent 调用开始与结束。
  - `message`：AI/命令最终输出片段。
  - `done`：最终汇总（与非流式 JSON 结构一致）。
  - `error`：任务失败或取消。
- WebChat 不发布模型 token 级文本增量，也不发布工具参数增量；正文以 `message` 事件展示，工具只按生命周期事件展示。
- 工具结束事件 payload 会尽量带 `duration_ms`，用于 WebUI 在工具 / Agent 名称旁显示本次调用耗时；运行中的 job 快照会在 `current_tool_calls` 中返回仍在执行的工具 / Agent 及其后端计算的 `duration_ms`。WebUI 每 0.5 秒查询一次，查询间隙只用本地时间临时递增显示，下一次查询后以 Runtime 返回值校准；结束后固定展示结束事件的总耗时。并发工具按实际完成时间发布结束事件，LLM tool message 回填仍保持模型要求的原始顺序。`done` / `error` payload 会带 `duration_ms` 表示整轮 job 总耗时。总耗时从 job 创建开始计，到 `done`/`error`/`cancelled` 收尾为止。
- 工具 / Agent 事件 payload 由后端补齐调用链字段：`webchat_call_id`、`parent_webchat_call_id`、`depth`、`agent_path`。Agent 内部工具、子 Agent 和 Agent 内发送的正文会以父子关系和 timeline 嵌套，前端只按这些字段展示。
- 工具 / Agent 事件 payload 由后端补齐 `status`，取值通常为 `running`、`done`、`error`、`cancelled`。WebUI 会按状态给调用块左侧状态条分色：运行中、成功、失败 / 取消分别使用不同提示色。如果 job 失败或取消时仍有未闭合调用，历史 metadata 会在统一落盘阶段补齐失败 / 取消终态，避免刷新后继续显示为运行中。
- WebUI 展开工具 / Agent 调用块时，会按输入 / 输出分区展示由 Runtime 生成的 `arguments_preview` 和 `result_preview`。预览会递归遮蔽常见敏感字段名（如 `api_key`、`authorization`、`token`、`password`、`secret`、`cookie` 等）并按长度截断；结构化预览会渲染为带颜色的键值字段。预览不是权限边界，工具实现仍应避免把完整凭证写入结果正文。
- 工具事件 payload 可能带 `ui_hint`。当前用于 WebChat 展示降噪：`webchat_private_send` 表示同一 WebChat 私聊回复已通过 `message` 事件展示，工具块只需显示发送状态；`webchat_end` 表示 `end` 成功结束，工具块可隐藏重复的成功结果。

行为约定：

- 会话固定虚拟用户：`system`（`id = 42`）。
- 权限视角：`superadmin`。
- 如果输入以 `/` 开头，按私聊命令分发执行（遵循命令 `allow_in_private` 开放策略）。

### WebUI AI Chat 历史记录

- `GET /api/v1/chat/history?limit=50&before=<cursor>`
- 用于分页读取虚拟私聊 `system#42` 的历史记录。默认返回最新一页，响应包含 `items/has_more/next_before/total`。
- 对于由 WebChat job 产生的回复，Bot 历史项可能包含 `webchat` 展示元数据：

```json
{
  "role": "bot",
  "content": "最终回复文本，可为空",
  "timestamp": "2026-05-30 12:00:00",
  "webchat": {
    "display_only": true,
    "job_id": "9c1...",
    "mode": "chat",
    "status": "done",
    "created_at": 1780123200.0,
    "finished_at": 1780123201.5,
    "duration_ms": 1500,
    "timeline": [
      {
        "type": "call",
        "seq": 2,
        "call": {
          "webchat_call_id": "call_agent",
          "name": "web_agent",
          "is_agent": true,
          "status": "done",
          "duration_ms": 900,
          "children": [
            {
              "webchat_call_id": "call_agent/call_search",
              "parent_webchat_call_id": "call_agent",
              "name": "search",
              "is_agent": false,
              "status": "done",
              "result_preview": "摘要",
              "duration_ms": 420,
              "children": []
            }
          ]
        }
      },
      {
        "type": "message",
        "seq": 4,
        "content": "中间回复文本",
        "elapsed_ms": 860
      }
    ],
    "calls": [
      {
        "webchat_call_id": "call_agent",
        "parent_webchat_call_id": "",
        "tool_call_id": "call_agent",
        "name": "web_agent",
        "is_agent": true,
        "status": "done",
        "duration_ms": 900,
        "children": [
          {
            "webchat_call_id": "call_agent/call_search",
            "parent_webchat_call_id": "call_agent",
            "tool_call_id": "call_search",
            "name": "search",
            "is_agent": false,
            "status": "done",
            "result_preview": "摘要",
            "duration_ms": 420,
            "children": []
          }
        ]
      }
    ],
    "events": [
      {
        "seq": 2,
        "event": "tool_start",
        "payload": {
          "job_id": "9c1...",
          "tool_call_id": "call_1",
          "name": "search",
          "arguments_preview": "{\"q\":\"test\"}",
          "is_agent": false
        }
      },
      {
        "seq": 4,
        "event": "message",
        "payload": {
          "job_id": "9c1...",
          "content": "中间回复文本"
        }
      },
      {
        "seq": 5,
        "event": "tool_end",
        "payload": {
          "job_id": "9c1...",
          "tool_call_id": "call_1",
          "name": "search",
          "ok": true,
          "duration_ms": 420,
          "result_preview": "摘要",
          "is_agent": false
        }
      }
    ]
  }
}
```

`webchat.timeline` 是后端生成的权威历史展示序列，按 `seq` 混排顶层工具 / Agent 调用节点与正文消息，前端刷新后优先按它忠实渲染同一 AI 气泡。`webchat.calls` 是后端由生命周期事件汇总出的调用树，包含每个工具 / Agent 的输入预览、输出预览、状态、耗时、`children` 和节点内 `timeline`；节点内 `timeline` 用于恢复 Agent 内部“子工具 / 子 Agent / 正文”的真实时序，Agent 阶段只恢复为摘要行状态。`webchat.events` 保留原始生命周期 / 正文事件，供兼容旧历史与诊断使用，不作为 AI 后续对话上下文注入。若一次 job 没有正文但有工具事件，历史 API 仍会返回该 Bot 项，`content` 为空字符串。
- `DELETE /api/v1/chat/history`
- 仅清空 `system#42` 聊天历史 JSON 和内存历史，不删除长期记忆、认知记忆或 profile。
- 如果存在运行中或正在收尾落盘的 WebChat job，返回 `409`，避免旧任务继续写回已清空的历史。

### WebUI AI Chat Jobs

- `POST /api/v1/chat/jobs`：创建后台 job，Body 为 `{"message":"..."}`。
- `GET /api/v1/chat/jobs/active`：返回当前运行中的 WebChat job（没有则为 `null`）。
- `GET /api/v1/chat/jobs/{job_id}`：查询 job 状态、最后事件序号和已汇总输出。
- `GET /api/v1/chat/jobs/{job_id}/events?after=<seq>`：查询 `seq` 之后的增量事件，默认返回 JSON。
- `GET /api/v1/chat/jobs/{job_id}/events?after=<seq>&format=json` 或请求头 `Accept: application/json`：显式查询 JSON。响应包含：

```json
{
  "job": {
    "job_id": "9c1...",
    "status": "running",
    "last_seq": 5,
    "elapsed_ms": 2400,
    "duration_ms": null,
    "current_stage": "waiting_tools",
    "current_stage_elapsed_ms": 1200,
    "current_agent_stages": [
      {
        "job_id": "9c1...",
        "webchat_call_id": "call_agent",
        "agent_name": "web_agent",
        "stage": "waiting_model",
        "stage_elapsed_ms": 900,
        "elapsed_ms": 2400,
        "transient": true
      }
    ],
    "current_tool_calls": [
      {
        "job_id": "9c1...",
        "webchat_call_id": "call_agent",
        "name": "web_agent",
        "status": "running",
        "is_agent": true,
        "started_at": 1760000000.0,
        "duration_ms": 2400,
        "current_stage": "waiting_model",
        "current_stage_elapsed_ms": 900
      }
    ]
  },
  "after": 5,
  "last_seq": 5,
  "events": [
    {
      "seq": 5,
      "event": "agent_stage",
      "payload": {
        "webchat_call_id": "call_agent",
        "stage": "waiting_model",
        "stage_elapsed_ms": 900,
        "transient": true
      }
    }
  ]
}
```

`events` 只包含 `after` 之后的持久事件以及当前运行阶段快照。快照使用当前 `last_seq`，便于刷新或断线后以 `job_id + seq` 轮询续接，但不会推进序号或重复写入历史。

Runtime 在同一个 job 条件锁内维护事件、顶层阶段、Agent 阶段和耗时快照，因此 JSON 查询和兼容 SSE 都应看到一致的 job 状态。
- `GET /api/v1/chat/jobs/{job_id}/events?after=<seq>` 加请求头 `Accept: text/event-stream`：兼容 SSE 订阅；SSE 帧包含 `id: <seq>`，长时间无事件时会发送 keep-alive 注释帧。
- `POST /api/v1/chat/jobs/{job_id}/cancel`：取消运行中的 job。

Runtime API 进程重启后不会恢复未完成 job；已落盘的聊天历史仍可通过 history 接口读取。

### 工具调用 API

需要在配置中显式开启 `tool_invoke_enabled = true`。未开启时所有工具调用端点返回 `403`。

#### 列出可用工具

- `GET /api/v1/tools`

返回经 `expose` / `allowlist` / `denylist` 三层过滤后的可用工具列表，每个条目为 OpenAI function calling 格式的 schema。

响应示例：

```json
{
  "count": 5,
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_current_time",
        "description": "获取当前系统时间",
        "parameters": { "type": "object", "properties": { ... } }
      }
    }
  ]
}
```

#### 调用指定工具

- `POST /api/v1/tools/invoke`

请求体：

```json
{
  "tool_name": "scheduler.create_schedule_task",
  "args": { "description": "...", "cron": "0 9 * * *" },
  "context": {
    "request_type": "group",
    "group_id": 123456,
    "user_id": 789,
    "sender_id": 789
  },
  "callback": {
    "enabled": true,
    "url": "https://example.com/callback",
    "headers": { "X-Secret": "xxx" }
  }
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `tool_name` | 是 | 工具全名（须在已过滤的可用列表中） |
| `args` | 是 | 工具参数（JSON 对象） |
| `context` | 否 | 请求上下文，不传时使用 `request_type="api"` 的虚拟上下文 |
| `callback` | 否 | 回调配置，启用后异步执行并将结果 POST 到 webhook URL |

`context` 子字段：

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `request_type` | `string` | 请求来源类型，默认 `"api"`；也可传 `"group"` 或 `"private"` 模拟群聊/私聊上下文 |
| `group_id` | `int` | 群号（`request_type="group"` 时使用） |
| `user_id` | `int` | 用户 QQ 号（工具根据此值查询历史/侧写等） |
| `sender_id` | `int` | 发送者 QQ 号（用于权限判断） |

`callback` 子字段：

| 子字段 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `enabled` | `bool` | 是 | 是否启用回调 |
| `url` | `string` | 是（当 enabled=true） | webhook URL（支持 HTTP 和 HTTPS） |
| `headers` | `object` | 否 | 自定义回调请求头（键值对） |

**同步响应**（无回调）：

```json
{
  "ok": true,
  "request_id": "uuid",
  "tool_name": "get_current_time",
  "result": "2026-03-13T12:00:00+08:00",
  "duration_ms": 15.2
}
```

**异步响应**（启用回调）：

```json
{
  "ok": true,
  "request_id": "uuid",
  "tool_name": "get_current_time",
  "status": "accepted"
}
```

回调 POST 到 webhook URL 的 body：

```json
{
  "request_id": "uuid",
  "tool_name": "get_current_time",
  "ok": true,
  "result": "...",
  "duration_ms": 15.2,
  "error": null
}
```

**错误响应**（工具执行失败或超时）：

```json
{
  "ok": false,
  "request_id": "uuid",
  "tool_name": "get_current_time",
  "error": "Execution timed out after 120s",
  "duration_ms": 120001.5
}
```

#### 错误状态码

| 状态码 | 含义 |
|--------|------|
| `400` | 请求体格式错误（缺少 `tool_name`、`args` 非对象、回调 URL 不合法等） |
| `401` | 鉴权失败（`X-Undefined-API-Key` 缺失或不匹配） |
| `403` | 工具调用 API 未启用（`tool_invoke_enabled = false`） |
| `404` | 指定的工具不在可用列表中（被 `denylist` / `expose` 过滤掉） |

#### 工具过滤逻辑

过滤优先级：`denylist` > `allowlist` > `expose`。

- `denylist` 非空时，先排除匹配项。
- `allowlist` 非空时，仅保留匹配项（忽略 `expose`）。
- 否则按 `expose` 范围过滤：
  - `tools`：仅基础工具（名称不含 `.`）
  - `toolsets`：仅工具集工具（名称含 `.` 且非 `mcp.` 前缀）
  - `tools+toolsets`：基础工具 + 工具集（默认）
  - `agents`：仅 Agent
  - `all`：全部（不含 anthropic_skills）

#### 回调 URL 要求

- 支持 HTTP 和 HTTPS（scheme 必须为 `http://` 或 `https://`，不接受 `ftp://` 等其他协议）。
- 直接使用私网/回环/链路本地 IP 字面量会被拒绝（如 `127.0.0.1`、`10.x`、`192.168.x`、`::1`）；域名形式可通过校验。
- 回调超时由 `tool_invoke_callback_timeout` 独立控制。
- 回调失败不影响工具调用的执行结果，仅记录日志 `[ToolInvoke] 回调失败`。

## 5. cURL 示例

```bash
API="http://127.0.0.1:8788"
KEY="changeme"

curl -H "X-Undefined-API-Key: $KEY" "$API/api/v1/probes/internal"
curl -H "X-Undefined-API-Key: $KEY" "$API/api/v1/memory?q=偏好"
curl -H "X-Undefined-API-Key: $KEY" "$API/api/v1/cognitive/profiles?q=user"
curl -H "X-Undefined-API-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"message":"/help"}' \
  "$API/api/v1/chat"

curl -N -H "X-Undefined-API-Key: $KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"message":"你好","stream":true}' \
  "$API/api/v1/chat"

JOB_ID="$(curl -s -H "X-Undefined-API-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"message":"你好"}' \
  "$API/api/v1/chat/jobs" | jq -r .job_id)"
curl -H "X-Undefined-API-Key: $KEY" \
  "$API/api/v1/chat/jobs/$JOB_ID/events?after=0&format=json"

curl -N -H "X-Undefined-API-Key: $KEY" \
  -H "Accept: text/event-stream" \
  "$API/api/v1/chat/jobs/$JOB_ID/events?after=0"

# 列出可用工具（需 tool_invoke_enabled = true）
curl -H "X-Undefined-API-Key: $KEY" "$API/api/v1/tools"

# 同步调用工具
curl -X POST -H "X-Undefined-API-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"tool_name":"get_current_time","args":{"format":"iso"}}' \
  "$API/api/v1/tools/invoke"

# 带回调的异步调用
curl -X POST -H "X-Undefined-API-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"tool_name":"get_current_time","args":{},"callback":{"enabled":true,"url":"https://webhook.site/xxx"}}' \
  "$API/api/v1/tools/invoke"
```

## 6. WebUI 代理调用（推荐）

WebUI 不直接在前端暴露 `auth_key`，而是通过后端代理访问主进程 Runtime API：

- `GET /api/runtime/probes/internal`
- `GET /api/runtime/probes/external`
- `GET /api/runtime/memory`
- `GET /api/runtime/cognitive/events`
- `GET /api/runtime/cognitive/profiles`
- `GET /api/runtime/cognitive/profile/{entity_type}/{entity_id}`
- `POST /api/runtime/chat`
- `GET /api/runtime/chat/history`
- `DELETE /api/runtime/chat/history`
- `POST /api/runtime/chat/jobs`
- `GET /api/runtime/chat/jobs/active`
- `GET /api/runtime/chat/jobs/{job_id}`
- `GET /api/runtime/chat/jobs/{job_id}/events`
- `POST /api/runtime/chat/jobs/{job_id}/cancel`
- `GET /api/runtime/openapi`
- `GET /api/runtime/tools`
- `POST /api/runtime/tools/invoke`

WebUI 后端会自动从 `config.toml` 读取 `[api].auth_key` 并注入 Header。
`/api/runtime/chat/jobs/{job_id}/events` 默认代理 JSON 增量查询；显式请求 `Accept: text/event-stream` 时会透传 SSE keep-alive，聊天代理超时按当前聊天模型队列预算计算。

## 7. 故障排查

- 返回 `401 Unauthorized`：
  - `auth_key` 错误或请求头缺失。
- 返回 `503 Runtime API disabled`：
  - `[api].enabled = false`。
- WebUI 显示 `Runtime API unreachable`：
  - 主进程未启动或监听地址/端口配置不一致。
- `openapi.json` 返回 `404`：
  - `[api].openapi_enabled = false`。
- `/api/v1/tools` 或 `/api/v1/tools/invoke` 返回 `403`：
  - `[api].tool_invoke_enabled = false`，需在配置中显式设为 `true`。
- `/api/v1/tools/invoke` 返回 `404`（Tool not available）：
  - 工具被 `denylist` 排除，或不在 `allowlist` / `expose` 范围内。
  - 使用 `GET /api/v1/tools` 查看当前实际可用的工具列表。
- 回调请求失败（日志 `[ToolInvoke] 回调失败`）：
  - 检查回调 URL 是否可达、证书是否有效。
  - 可通过 `tool_invoke_callback_timeout` 调整超时。

## 8. Naga 集成端点

Naga 集成端点仅在以下条件同时满足时注册：

- `[api].enabled = true`
- `[features].nagaagent_mode_enabled = true`
- `[naga].enabled = true`

这些端点**不走主 API Key 中间件**，统一使用 `Authorization: Bearer {config.[naga].api_key}` 鉴权。

### 当前端点

| 路径 | 作用 |
|------|------|
| `POST /api/v1/naga/bind/callback` | Naga 异步确认某个 `bind_uuid` 的绑定结果 |
| `POST /api/v1/naga/messages/send` | Naga 验签后向“绑定 QQ + 绑定群”发送消息 |
| `POST /api/v1/naga/unbind` | Naga 主动吊销已有绑定 |

### 协议说明

- 绑定流程使用 `bind_uuid` 驱动，而不是早期的 scoped token。
- 发送流程使用 `bind_uuid + naga_id + delivery_signature` 三元组验签。
- 发送流程支持调用方提供 `uuid` 作为幂等键；相同键的重复请求会直接复用首个结果。
- `target.qq_id` / `target.group_id` 必须显式提供，并且必须等于已绑定目标。
- `target.mode` 支持 `private` / `group` / `both`。
- `message.format` 支持 `text` / `markdown` / `html`。
- 发送前会进行一次审核；命中风险时返回 `403`，审核模型异常/超时时 fail-open，并在响应中返回 `moderation.status=error_allowed`。
- 若 `config.[naga].moderation_enabled = false`，则直接跳过审核，并返回 `moderation.status=skipped_disabled`。
- `markdown` / `html` 会优先尝试渲染成图片；渲染失败时会回退为文本发送，并在响应中返回 `render_fallback=true`。
- 当 `mode=both` 时，只要私聊或群聊至少有一个成功，接口仍返回 `200`，由 `sent_private` / `sent_group` 指示实际投递结果。
- 成功响应会额外返回 `partial_success` 与 `delivery_status`：完全成功时为 `false` / `full_success`，部分成功时为 `true` / `partial_success`。

### 典型错误码

| 状态码 | 含义 |
|--------|------|
| `400` | 请求体格式错误、缺少必填字段 |
| `401` | `Authorization` 缺失或共享密钥错误 |
| `403` | `bind_uuid` / `delivery_signature` / target 不匹配，群不在白名单，或审核拦截 |
| `404` | `bind/callback` 所需的 pending 不存在 |
| `409` | 状态冲突，例如绑定代际不一致、请求已被其他结果终结 |
| `502` | 目标投递全部失败 |
| `503` | Naga 集成未就绪 |

### 进一步阅读

完整请求体、响应体和双向调用约定见：

- [docs/naga_integration_contract.md](/data0/Undefined/docs/naga_integration_contract.md)
