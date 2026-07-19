# Runtime API / OpenAPI 指南

本文档说明 Undefined 主进程暴露的 Runtime API（含 OpenAPI 文档），以及 WebUI / App 如何通过 Management API 代理或原生客户端安全调用。

> 职责边界：
>
> - **Management API**：配置、日志、Bot 启停、bootstrap probe、远程管理入口
> - **Runtime API**：主进程运行态能力（探针、记忆、认知、AI Chat、表情包库）
>
> 如果你想看控制面接口，请同时参考 [Management API 文档](management-api.md)。如果你要接入原生聊天客户端，请参考 [Undefined Chat](undefined-chat.md)。

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
| `scheduler` | `object` | 定时任务调度摘要（`available`、`count`、`running`） |
| `api` | `object` | Runtime API 配置（`enabled`、`host`、`port`、`openapi_enabled`） |
| `skills` | `object` | 技能统计，包含 `tools`、`toolsets`、`agents`、`pipelines`、`commands`、`anthropic_skills` 子对象 |
| `models` | `object` | 模型配置；生成模型包含 `model_name`、脱敏 `api_url`、canonical `api_mode`（`openai.chat_completions` / `openai.responses` / `anthropic.messages`）、`thinking_enabled`、`thinking_tool_call_compat`、`reasoning_content_replay`、`system_prompt_as_user`、`responses_tool_choice_compat`、`responses_force_stateless_replay`、`prompt_cache_enabled`、`reasoning_enabled`、`reasoning_effort` |

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
    "api_mode": "openai.responses",
    "thinking_enabled": false,
    "thinking_tool_call_compat": true,
    "reasoning_content_replay": true,
    "system_prompt_as_user": false,
    "responses_tool_choice_compat": false,
    "responses_force_stateless_replay": false,
    "reasoning_enabled": true,
    "reasoning_effort": "high"
  },
  "embedding_model": { "model_name": "text-embedding-3-small", "api_url": "https://api.example.com/..." }
}
```

说明：`reasoning_content_replay` 默认开启；关闭后不会向上游发送明文、summary、签名或加密推理材料。`responses_tool_choice_compat` 与 `responses_force_stateless_replay` 通常保持 `false`，仅在 `openai.responses` 兼容网关不支持官方对象型工具选择或状态续轮时尝试开启。

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

### 定时任务

- `GET /api/v1/schedules`
- `POST /api/v1/schedules`
- `GET /api/v1/schedules/{task_id}`
- `PATCH /api/v1/schedules/{task_id}`
- `DELETE /api/v1/schedules/{task_id}`

`GET /api/v1/schedules` 返回：

```json
{
  "count": 1,
  "items": [
    {
      "task_id": "task_daily_report",
      "task_name": "每日摘要",
      "mode": "self_instruction",
      "cron": "0 9 * * *",
      "address": "group:123456",
      "target_type": "group",
      "target_id": 123456,
      "tool_name": "scheduler.call_self",
      "tool_args": { "prompt": "总结昨天群里的待办。" },
      "self_instruction": "总结昨天群里的待办。",
      "max_executions": null,
      "current_executions": 0,
      "next_run_time": "2026-06-07T09:00:00+08:00"
    }
  ]
}
```

创建和更新任务使用相同的 JSON 字段；`PATCH` 只提交需要修改的字段即可。`mode` 支持：

| mode | 必填字段 | 说明 |
|---|---|---|
| `single` | `tool_name`、`tool_args` | 定时调用单个工具 |
| `multi` | `tools`、`execution_mode` | 定时串行或并行调用多个工具 |
| `self_instruction` | `self_instruction` | 在触发时唤醒 AI 自身执行自然语言指令 |

通用字段：

| 字段 | 说明 |
|---|---|
| `task_id` | 创建时可选；不传时自动生成。新建 ID 只允许字母、数字、`_`、`.`、`:`、`-`，最长 96 字符；已有历史任务即使 ID 含中文，也可继续通过详情、更新和删除接口管理 |
| `task_name` | 可选的可读名称 |
| `cron_expression` | 标准 5 段 crontab 表达式；也兼容字段名 `cron` |
| `address` | 推荐的规范投递地址：`qq:<QQ号>`、`group:<群号>` 或 `wechat:<逻辑QQ号>`；`PATCH` 时传 `null` 可清空 |
| `target_type` | `group` 或 `private`，默认 `group` |
| `target_id` | 可选的发送目标 ID；`PATCH` 时传 `null` 可清空 |
| `max_executions` | 可选的最大执行次数；`PATCH` 时传 `null` 可清空 |

创建“自我督办”任务：

```json
{
  "task_id": "task_daily_review",
  "task_name": "每日复盘",
  "cron_expression": "0 9 * * *",
  "mode": "self_instruction",
  "self_instruction": "请总结昨天的待办，并提醒我今天优先处理前三项。",
  "address": "wechat:12345678"
}
```

创建单工具任务：

```json
{
  "cron_expression": "*/30 * * * *",
  "mode": "single",
  "tool_name": "get_current_time",
  "tool_args": { "format": "iso" }
}
```

创建多工具任务：

```json
{
  "cron_expression": "0 8 * * 1",
  "mode": "multi",
  "execution_mode": "serial",
  "tools": [
    { "tool_name": "get_current_time", "tool_args": {} },
    { "tool_name": "scheduler.call_self", "tool_args": { "prompt": "生成本周计划。" } }
  ]
}
```

说明：
- `tool_name`、`tools`、`self_instruction` 互斥；显式传 `mode` 时也必须与对应字段一致。
- 历史任务如果保存为单个 `scheduler.call_self` 工具调用，列表和详情会按 `self_instruction` 模式返回，并从 `prompt` 回填 `self_instruction`。
- `tool_args` 必须是 JSON 对象；`tools` 必须是非空数组，最多 20 项。
- 所有 `/api/v1/schedules*` 路由都遵循 Runtime API 的 `X-Undefined-API-Key` 鉴权。

### 微信 ClawBot / iLink

- `GET /api/v1/weixin`：服务、帐号连接状态和媒体能力。
- `POST /api/v1/weixin/login`：创建二维码登录会话。Body 为 `{"alias":"primary","qq_id":12345678}`；管理员身份首次提交返回 `409`、警告与 `confirmation_token`，第二次提交同一参数及 token 后继续。
- `GET /api/v1/weixin/login/{session_id}`：查询扫码、验证码、确认或过期状态。
- `GET /api/v1/weixin/login/{session_id}/qr.png`：二维码 PNG，响应禁止缓存。
- `POST /api/v1/weixin/login/{session_id}/refresh`：刷新二维码。
- `POST /api/v1/weixin/login/{session_id}/verify`：提交 `{"code":"123456"}`。
- `DELETE /api/v1/weixin/login/{session_id}`：取消未完成的登录会话。
- `PATCH /api/v1/weixin/accounts/{alias}`：提交 `{"enabled":false}` 启停帐号，或提交 `{"qq_id":12345678}` 改绑逻辑身份；高权限改绑同样要求二次确认。
- `DELETE /api/v1/weixin/accounts/{alias}`：停止帐号并删除本地绑定凭据。
- `GET /api/v1/weixin/pending` / `DELETE /api/v1/weixin/pending/{record_id}`：查看或忽略未知来源隔离记录。
- `GET /api/v1/weixin/audit?limit=100`：读取最近帐号管理审计。

公开响应不会返回 iLink token、account ID、peer ID 或二维码原始载荷。所有端点都遵循 Runtime API Key 鉴权；WebUI 使用 Management 代理。身份映射、安全边界和媒体限制见 [微信 iLink 接入](wechat-ilink.md)。

### 认知记忆检索 / 侧写

- `GET /api/v1/cognitive/events?q=...`
  - 额外支持：`target_user_id`、`target_group_id`、`sender_id`、`request_type`、`top_k`、`time_from`、`time_to`
- `GET /api/v1/cognitive/profiles?q=...`
  - 额外支持：`entity_type`、`top_k`
- `GET /api/v1/cognitive/profile/{entity_type}/{entity_id}`

说明：这些接口仅在 `cognitive.enabled = true` 时可用，否则返回错误。

### 斜杠命令元数据

- `GET /api/v1/commands`
- `GET /api/v1/commands/{command_name}`

查询参数：

- `scope`：`webui` / `private` / `group`，默认 `webui`。`webui` 会按 WebChat 虚拟私聊的实际执行路径过滤：身份仍是 `system#42`，权限主体使用配置中的 `superadmin_qq`。
- `q`：按命令名、别名、描述、用法和子命令过滤（可选）。
- `include_hidden`：是否包含 `show_in_help=false` 的命令，默认 `false`。
- `include_unavailable`：是否返回当前 scope / 权限下不可用的命令，并在 `unavailable_reason` 标明原因，默认 `false`。
- `sender_id` / `user_id` / `group_id`：当 `scope=private` 或 `scope=group` 时可指定用于权限和可见性策略判断的身份。

响应包含 `commands[]`。命令项提供 `name`、`trigger`、`description`、`usage`、`example`、`permission`、`allow_in_private`、`aliases`、`alias_triggers`、`subcommands[]`、`inference`、`available` 和 `unavailable_reason`；子命令项提供 `name`、`trigger`、`description`、`args`、`usage`、`permission`、`allow_in_private`、`available` 和 `unavailable_reason`。WebUI 的 `/` 补全面板使用 `GET /api/v1/commands?scope=webui`，因此展示结果与 WebChat 实际命令分发保持一致。

### WebUI AI Chat 导览

- [WebUI AI Chat（特殊私聊）](#webui-ai-chat特殊私聊)
- [Event types](#event-types)
- [WebUI AI Chat Conversations](#webui-ai-chat-conversations)
- [WebUI AI Chat 历史记录](#webui-ai-chat-历史记录)
- [WebUI AI Chat Jobs](#webui-ai-chat-jobs)
- [Schemas / Appendix](#schemas--appendix)

Undefined Chat 使用同一组 Runtime Chat 端点作为权威合同。客户端可以直接访问 Runtime API，并由 Tauri 负责 API Key 注入、安全存储、SSE 订阅、JSON fallback、上传下载和 HTML 预览隔离；不能把本地草稿或前端缓存视为会话/历史真源。

### WebUI AI Chat（特殊私聊）

- `POST /api/v1/chat`
- Body：

```json
{
  "message": "你好",
  "conversation_id": "legacy-system-42",
  "stream": false
}
```

- `stream = false` 返回同步 JSON，但后端同样会创建 WebChat job 并等待其完成；同一会话运行中或收尾落盘时再次发送会返回 `409`，不同会话可以并发运行。
- 当 `stream = true` 时，Runtime 会创建 WebChat job 并通过旧接口返回 SSE；WebUI 默认使用 job 查询接口续接事件。
- `conversation_id` 可选；不传时使用兼容默认会话 `legacy-system-42`，传入不存在的会话 ID 时返回 `404`。
#### Event types

- `meta`：会话元信息。
- `stage`：顶层 AI 当前处理阶段，用于 WebUI 在 `AI` 标签后实时显示状态和总已用时；payload 形如 `{"job_id":"...","stage":"waiting_model","elapsed_ms":1234,"detail":"..."}`。
- `agent_stage`：某个 Agent 内部当前阶段，payload 包含 `webchat_call_id`、`stage`、`stage_elapsed_ms`、`elapsed_ms`、`agent_name`。运行中查询可能返回 `transient=true` 的当前快照；这类快照不写入历史。
- `tool_start` / `tool_end`：工具开始与结束。
- `agent_start` / `agent_end`：Agent 调用开始与结束。
- `requires_action`：预留给未来 Human-in-the-loop 授权、补充参数或确认动作；payload 会做敏感字段遮蔽，并保留在 job events 与 history `webchat.events` 中。
- `message`：AI/命令最终输出片段。
- `done`：最终汇总（与非流式 JSON 结构一致）。
- `error`：任务失败或取消。

#### Lifecycle / Display Conventions

- WebChat 不发布模型 token 级文本增量，也不发布工具参数增量；正文以 `message` 事件展示，工具只按生命周期事件展示。
- `stage`、`agent_stage`、`webchat.calls`、`webchat.timeline`、`current_tool_calls` 和 `duration_ms` 是 display-only 展示元数据，不作为 AI-context 注入后续对话。
- 工具结束事件 payload 会尽量带 `duration_ms`。运行中的 job 快照会在 `current_tool_calls` 返回仍在执行的工具 / Agent 及其后端计算的 `duration_ms`。
- WebUI 每 0.5 秒查询一次；查询间隙只用本地时间临时递增显示，下一次查询后以 Runtime 返回值校准。
- 并发工具按实际完成时间发布结束事件，LLM tool message 回填仍保持模型要求的原始顺序。
- 工具 / Agent 事件 payload 由后端补齐调用链字段：`webchat_call_id`、`parent_webchat_call_id`、`depth`、`agent_path`。
- 工具 / Agent 事件 payload 由后端补齐 `status`，取值通常为 `running`、`done`、`error`、`cancelled`。如果 job 失败或取消时仍有未闭合调用，历史 metadata 会在统一落盘阶段补齐失败 / 取消终态。
- WebUI 展开工具 / Agent 调用块时，会按输入 / 输出分区展示由 Runtime 生成的 `arguments_preview` 和 `result_preview`。预览会递归遮蔽常见敏感字段并按长度截断；预览不是权限边界，工具实现仍应避免把完整凭证写入结果正文。
- 工具事件 payload 可能带 `ui_hint`：`webchat_private_send` 表示同一 WebChat 私聊回复已通过 `message` 事件展示；`webchat_end` 表示 `end` 成功结束，工具块可隐藏重复的成功结果。

行为约定：

- AI 视角固定虚拟私聊身份：`system`（`id = 42`）。多对话只隔离 WebChat 历史文件和前端列表，不改变 `RequestContext`、`sender_id`、`user_id`、权限或 AI 看到的用户身份。
- 权限视角：`superadmin`。
- 如果输入以 `/` 开头，按私聊命令分发执行（遵循命令 `allow_in_private` 开放策略）。
- WebChat 会话持久化在 `data/webchat/conversations/<conversation_id>.json`，一个会话一个 JSON 文件。删除会话会删除对应 JSON；不会写入单个全局 conversations JSON。
- 首次加载会自动把旧版 `data/history/private_42.json` 或运行中的旧历史管理器记录迁移到 `legacy-system-42`，并写入 `data/webchat/legacy_private_42_migrated.json` 迁移标记。只要标记存在就不会重复迁移；即使删除迁移出的会话，也不会再次从旧文件恢复。

### WebUI AI Chat Conversations

- `GET /api/v1/chat/conversations`：列出 WebChat 会话，响应包含 `conversations`、`active_job`、`default_conversation_id` 和 `virtual_user_id`。
- `POST /api/v1/chat/conversations`：新建会话，Body 可选 `{"title":"..."}`。不传标题时先使用临时标题。
- `PATCH /api/v1/chat/conversations/{conversation_id}`：重命名会话，Body 为 `{"title":"..."}`。手动标题会标记为 `manual`，后续不会被自动标题覆盖。
- `DELETE /api/v1/chat/conversations/{conversation_id}`：删除会话 JSON。若目标会话存在运行中或收尾落盘的 WebChat job，返回 `409`。

会话标题由后端维护。第一条用户消息写入后会先用首问前若干字符作为临时标题；当该会话同时具备首问和首答时，后端会调标题生成模型用“首问 + 首答”生成正式标题。标题生成带状态和内容哈希校验，避免并发回复、手动重命名或历史变化时把旧标题写回新内容。

### WebUI AI Chat 历史记录

- `GET /api/v1/chat/history?conversation_id=<id>&limit=50&before=<cursor>`
- 用于分页读取指定 WebChat 会话的虚拟私聊 `system#42` 历史记录。默认返回最新一页，响应包含 `conversation_id/items/has_more/next_before/total`；客户端继续加载更早历史时把上次返回的 `next_before` 作为 `before` 传回。不传 `conversation_id` 时兼容读取默认会话。
- 对于由 WebChat job 产生的回复，Bot 历史项可能包含 `webchat` 展示元数据。完整示例见下方折叠块，字段 schema 见 [Schemas / Appendix](#schemas--appendix)。

<details>
<summary>展开完整 history 示例</summary>

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

</details>

`webchat.timeline` 是后端生成的权威历史展示序列，按 `seq` 混排顶层工具 / Agent 调用节点与正文消息，前端刷新后优先按它忠实渲染同一 AI 气泡。`webchat.calls` 是后端由生命周期事件汇总出的调用树，包含每个工具 / Agent 的输入预览、输出预览、状态、耗时、`children` 和节点内 `timeline`；节点内 `timeline` 用于恢复 Agent 内部“子工具 / 子 Agent / 正文”的真实时序，Agent 阶段只恢复为摘要行状态。`webchat.events` 保留原始生命周期 / 正文事件，供兼容旧历史与诊断使用，不作为 AI 后续对话上下文注入。若一次 job 没有正文但有工具事件，历史 API 仍会返回该 Bot 项，`content` 为空字符串。
- `DELETE /api/v1/chat/history?conversation_id=<id>`
- 仅清空指定 WebChat 会话的 `system#42` 聊天历史，不删除长期记忆、认知记忆、profile 或其他 WebChat 会话。
- 如果目标会话存在运行中或正在收尾落盘的 WebChat job，返回 `409`，避免旧任务继续写回已清空的历史。

### WebUI AI Chat Jobs

- `POST /api/v1/chat/jobs`：创建后台 job。兼容旧 Body `{"message":"...","conversation_id":"..."}`，也支持结构化 Body `{"message":{"text":"...","attachment_ids":["..."],"references":[{"message_id":"...","quote":"..."}]},"conversation_id":"..."}`；`conversation_id` 可选。取消后重试最后一条纯文本用户消息时，可传 `reuse_previous_user_message: true`，Runtime 会要求最后一条可见用户历史与本次文本完全一致，并跳过重复写入用户历史。
- WebChat job 在同一会话内 single-flight；如果目标会话已有 job 正在运行或收尾落盘，创建新 job 返回 `409`。不同会话可以并发运行。兼容的非流式 `POST /api/v1/chat` 也走同一套会话级 job 锁，只是等待完成后返回同步结果。
- 附件先通过 `POST /api/v1/chat/attachments` 以 multipart 上传并由 Runtime 返回附件 metadata；发送消息时只传 Runtime 生成的 `attachment_ids`。客户端不应把本地文件内容、下载 URL 或临时缓存路径拼入 `message.text`。
- 引用内容通过结构化 `references` 提交。Runtime 负责把引用写入历史 metadata，并按需要生成 AI 可见上下文；客户端不把引用块拼接进最终历史作为真源。
- `GET /api/v1/chat/jobs/active?conversation_id=<id>`：返回兼容字段 `job` 和 active `jobs[]`。不传时 `jobs[]` 包含所有运行中 WebChat job，`job` 为最新 active job；传入 `conversation_id` 时只返回目标会话的 active job。
- `GET /api/v1/chat/jobs/{job_id}`：查询 job 状态、最后事件序号和已汇总输出。
- `GET /api/v1/chat/jobs/{job_id}/events?after=<seq>&conversation_id=<id>`：查询 `seq` 之后的增量事件，默认返回 JSON。`conversation_id` 可选；传入时必须与 job 所属会话一致，否则返回 `404`，用于刷新、断线或换客户端后避免跨会话误续接。
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

### Schemas / Appendix

#### `webchat.events`

```json
[
  {
    "seq": 5,
    "event": "tool_end",
    "payload": {
      "job_id": "9c1...",
      "tool_call_id": "call_1",
      "webchat_call_id": "call_1",
      "parent_webchat_call_id": "",
      "name": "search",
      "status": "done",
      "duration_ms": 420,
      "arguments_preview": "{\"q\":\"test\"}",
      "result_preview": "摘要"
    }
  }
]
```

#### `webchat.calls`

```json
[
  {
    "webchat_call_id": "call_agent",
    "parent_webchat_call_id": "",
    "name": "web_agent",
    "is_agent": true,
    "status": "done",
    "duration_ms": 900,
    "children": []
  }
]
```

#### History Response

```json
{
  "conversation_id": "legacy-system-42",
  "items": [
    {
      "role": "bot",
      "content": "最终回复文本",
      "webchat": {
        "display_only": true,
        "duration_ms": 1500,
        "timeline": [],
        "calls": [],
        "events": []
      }
    }
  ],
  "has_more": false,
  "next_before": null,
  "total": 1
}
```

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
- `GET /api/runtime/schedules`
- `POST /api/runtime/schedules`
- `GET /api/runtime/schedules/{task_id}`
- `PATCH /api/runtime/schedules/{task_id}`
- `DELETE /api/runtime/schedules/{task_id}`
- `GET /api/runtime/cognitive/events`
- `GET /api/runtime/cognitive/profiles`
- `GET /api/runtime/cognitive/profile/{entity_type}/{entity_id}`
- `GET /api/runtime/commands`
- `GET /api/runtime/commands/{command_name}`
- `GET /api/runtime/chat/conversations`
- `POST /api/runtime/chat/conversations`
- `PATCH /api/runtime/chat/conversations/{conversation_id}`
- `DELETE /api/runtime/chat/conversations/{conversation_id}`
- `POST /api/runtime/chat`
- `GET /api/runtime/chat/history`
- `DELETE /api/runtime/chat/history`
- `GET /api/runtime/chat/attachments/capabilities`
- `POST /api/runtime/chat/attachments`
- `GET /api/runtime/chat/attachments/{attachment_id}`
- `GET /api/runtime/chat/attachments/{attachment_id}/preview`
- `POST /api/runtime/chat/jobs`
- `GET /api/runtime/chat/jobs/active`
- `GET /api/runtime/chat/jobs/{job_id}`
- `GET /api/runtime/chat/jobs/{job_id}/events`
- `POST /api/runtime/chat/jobs/{job_id}/cancel`
- `POST /api/runtime/chat/files`（旧 WebUI 浏览器文件缓存兼容路径，新客户端使用 `chat/attachments`）
- `GET /api/runtime/openapi`
- `GET /api/runtime/tools`
- `POST /api/runtime/tools/invoke`

### Auth / Header 注入

WebUI 后端会先校验 WebUI 登录态，再自动从 `config.toml` 读取 `[api].auth_key` 并注入 `X-Undefined-API-Key`，前端只持有 WebUI 登录态，不直接暴露 Runtime API 密钥。

### Command Proxy

`/api/runtime/commands` 代理斜杠命令 REST 资源。

- WebChat 输入框的 `/` 补全默认请求 `scope=webui`。
- `q`、`include_hidden`、`include_unavailable` 等查询参数原样透传。

### Conversation Handling

`/api/runtime/chat/conversations` 代理 WebChat 多对话管理。

- `GET/POST/PATCH/DELETE /api/runtime/chat/conversations...` 管理会话 JSON。
- `/api/runtime/chat`、`/api/runtime/chat/history`、`/api/runtime/chat/jobs` 和 `/api/runtime/chat/jobs/active` 会透传 `conversation_id`。
- 不传 `conversation_id` 时使用 Runtime 默认兼容会话。
- 删除会话或清空历史时，目标会话运行中或收尾落盘中的 WebChat job 会导致 `409`。

### File Uploads

Undefined Chat 原生客户端直接使用 Runtime 附件端点；WebUI 代理层应优先透传这些端点：

- `GET /api/runtime/chat/attachments/capabilities`
- `POST /api/runtime/chat/attachments`
- `GET /api/runtime/chat/attachments/{attachment_id}`
- `GET /api/runtime/chat/attachments/{attachment_id}/preview`

上传使用 `multipart/form-data`，字段名为 `file`。Runtime 返回 `attachment.id`、`name`、`size`、`media_type`、`kind`、`download_url` 和可选 `preview_url`；发送消息时把这些 id 放进结构化 `message.attachment_ids`。引用内容放进结构化 `message.references`，由 Runtime 写入历史 metadata。

WebUI 浏览器端渲染 UID 附件图片时应使用代理路径 `/api/runtime/chat/attachments/{attachment_id}/preview`，不要把 Runtime 返回的 `/api/v1/chat/attachments/...` 直接放进 `<img>`。普通 Markdown 外链图片仍按安全 URL 白名单直接渲染为可点击预览图片。

### Event / Query Behavior

`/api/runtime/chat/jobs/{job_id}/events` 代理 WebChat job 事件续接。

- 默认返回 JSON 增量查询。
- `Accept: text/event-stream` 时透传 Runtime SSE 和 keep-alive。
- `conversation_id` 传入时必须与 job 所属会话一致。
- `after` 用于按 seq 增量续接。
- 聊天代理超时按当前聊天模型队列预算计算。

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
