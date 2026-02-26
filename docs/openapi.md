# Runtime API / OpenAPI 指南

本文档说明 Undefined 主进程暴露的 Runtime API（含 OpenAPI 文档），以及 WebUI 如何安全调用。

## 1. 配置项

在 `config.toml` 中使用 `[api]`：

```toml
[api]
enabled = true
host = "127.0.0.1"
port = 8788
auth_key = "changeme"
openapi_enabled = true
```

- `enabled`：是否启动 Runtime API。
- `host` / `port`：监听地址和端口。
- `auth_key`：API 鉴权密钥（请求头 `X-Undefined-API-Key`）。
- `openapi_enabled`：是否开放 `/openapi.json`。

默认值：

- `enabled = true`
- `host = 127.0.0.1`
- `port = 8788`
- `auth_key = changeme`
- `openapi_enabled = true`

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
| `models` | `object` | 模型配置，包含各模型的 `model_name`、脱敏 `api_url`、`thinking_enabled` |

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

`models` 子对象结构（URL 经脱敏处理，仅保留 scheme + host）：

```json
{
  "chat_model": { "model_name": "claude-sonnet-4-20250514", "api_url": "https://api.example.com/...", "thinking_enabled": false },
  "embedding_model": { "model_name": "text-embedding-3-small", "api_url": "https://api.example.com/..." }
}
```

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
