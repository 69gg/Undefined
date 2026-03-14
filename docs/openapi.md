# Runtime API / OpenAPI 指南

本文档说明 Undefined 主进程暴露的 Runtime API（含 OpenAPI 文档），以及 WebUI / App 如何通过 Management API 代理安全调用。

> 职责边界：
>
> - **Management API**：配置、日志、Bot 启停、bootstrap probe、远程管理入口
> - **Runtime API**：主进程运行态能力（探针、记忆、认知、AI Chat）
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

- 所有 `/api/*` 路由都要求请求头：

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
| `queues` | `object` | 请求队列快照（`processor_count`、`inflight_count`、`totals` 按优先级分布） |
| `memory` | `object` | 长期记忆（`count`：条数） |
| `cognitive` | `object` | 认知服务（`enabled`、`queue`） |
| `api` | `object` | Runtime API 配置（`enabled`、`host`、`port`、`openapi_enabled`） |
| `skills` | `object` | 技能统计，包含 `tools`、`agents`、`anthropic_skills` 三个子对象 |
| `models` | `object` | 模型配置；聊天类模型包含 `model_name`、脱敏 `api_url`、`api_mode`、`thinking_enabled`、`thinking_tool_call_compat`、`responses_tool_choice_compat`、`responses_force_stateless_replay`、`reasoning_enabled`、`reasoning_effort` |

`skills` 子对象结构：

```json
{
  "count": 12,
  "loaded": 12,
  "items": [
    { "name": "get_time", "loaded": true, "calls": 5, "success": 5, "failure": 0 }
  ]
}
```

`models` 子对象结构（URL 经脱敏处理，仅保留 scheme + host；embedding/rerank 仅返回 `model_name` 与 `api_url`）：

```json
{
  "chat_model": {
    "model_name": "claude-sonnet-4-20250514",
    "api_url": "https://api.example.com/...",
    "api_mode": "responses",
    "thinking_enabled": false,
    "thinking_tool_call_compat": true,
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
| `ok` | `bool` | 全部端点是否正常 |
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
| `host` / `port` | `string` / `int` | WebSocket 端点的主机与端口 |

### 记忆（只读）

- `GET /api/v1/memory`
- 查询参数：`q`（可选，关键字过滤）

说明：仅提供查看/查询，不提供写入接口，不改变现有记忆存储格式。

### 认知记忆检索 / 侧写

- `GET /api/v1/cognitive/events?q=...`
- `GET /api/v1/cognitive/profiles?q=...`
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

- 当 `stream = true` 时，返回 `text/event-stream`（SSE）：
  - `event: meta`：会话元信息。
  - `event: message`：AI/命令输出片段。
  - `event: done`：最终汇总（与非流式 JSON 结构一致）。
  - 在长时间无内容时会发送 `: keep-alive` 注释帧，防止中间层空闲断连。

行为约定：

- 会话固定虚拟用户：`system`（`id = 42`）。
- 权限视角：`superadmin`。
- 如果输入以 `/` 开头，按私聊命令分发执行（遵循命令 `allow_in_private` 开放策略）。

### WebUI AI Chat 历史记录

- `GET /api/v1/chat/history?limit=200`
- 用于读取虚拟私聊 `system#42` 的历史记录（只读）。
- 返回中包含 `role/content/timestamp`，用于 WebUI 自动恢复会话视图。

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
- `GET /api/runtime/openapi`
- `GET /api/runtime/tools`
- `POST /api/runtime/tools/invoke`

WebUI 后端会自动从 `config.toml` 读取 `[api].auth_key` 并注入 Header。
`/api/runtime/chat` 代理超时为 `480s`，并透传 SSE keep-alive。

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

## 8. Naga 回调 API

Naga 集成端点仅在 `[naga].enabled = true` 时注册。这些端点**不走主 API Key 中间件**，使用独立的共享密钥鉴权。

### 配置

```toml
[naga]
enabled = false
api_url = ""
api_key = ""
allowed_groups = []
```

### 鉴权模型（双层）

| 层级 | 作用 | 传递方式 |
|------|------|---------|
| 共享密钥 `api_key` | 服务器身份验证 | `Authorization: Bearer {api_key}` |
| Scoped Token `udf_xxx` | 绑定级别验证（per naga_id） | body 中 `token` 字段或 `X-Naga-Token` header |

### POST /api/v1/naga/callback — 消息回调

Naga 服务器调用此端点向绑定的 QQ 用户/群发送消息。

请求体：

```json
{
  "naga_id": "alice",
  "token": "udf_xxx",
  "message": {
    "format": "text",
    "content": "hello"
  }
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `naga_id` | 是 | 绑定标识 |
| `token` | 是 | scoped token（`udf_` 前缀） |
| `message.format` | 是 | `text` / `markdown` / `html` |
| `message.content` | 是 | 消息内容 |

发送逻辑：
- 私聊发给绑定的 QQ 用户（总开关开即可）
- 群聊发到绑定时的群（该群须仍在 `allowed_groups` 内）
- `markdown` / `html` 格式会渲染为图片发送

响应：

```json
{
  "ok": true,
  "sent_private": true,
  "sent_group": true
}
```

### GET /api/v1/naga/targets — 查询发送目标

查询某个 naga_id 绑定的 QQ 用户和可用群。

请求：

```http
GET /api/v1/naga/targets?naga_id=alice
Authorization: Bearer {api_key}
X-Naga-Token: udf_xxx
```

响应：

```json
{
  "naga_id": "alice",
  "bound_qq": 123456,
  "groups": [
    { "group_id": 789, "group_name": "测试群" }
  ]
}
```

### 错误状态码

| 状态码 | 含义 |
|--------|------|
| `400` | 请求体格式错误（缺少必填字段、format 不合法等） |
| `401` | 共享密钥校验失败 |
| `403` | scoped token 不匹配、绑定已吊销、或群不在白名单 |
| `503` | Naga 集成未就绪 |

### cURL 示例

```bash
NAGA_KEY="your_shared_key"
API="http://127.0.0.1:8788"

# 消息回调
curl -X POST \
  -H "Authorization: Bearer $NAGA_KEY" \
  -H "Content-Type: application/json" \
  -d '{"naga_id":"alice","token":"udf_xxx","message":{"format":"text","content":"hello"}}' \
  "$API/api/v1/naga/callback"

# 查询目标
curl -H "Authorization: Bearer $NAGA_KEY" \
  -H "X-Naga-Token: udf_xxx" \
  "$API/api/v1/naga/targets?naga_id=alice"
```
