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

- `GET /api/v1/probes/internal`：进程内部探针（OneBot 连接、队列、记忆计数、认知队列等）。
- `GET /api/v1/probes/external`：外部依赖探测（模型 API 与 OneBot 端口连通）。

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
  "message": "你好"
}
```

行为约定：

- 会话固定虚拟用户：`system`（`id = 42`）。
- 权限视角：`superadmin`。
- 如果输入以 `/` 开头，按私聊命令分发执行（遵循命令 `allow_in_private` 开放策略）。

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
- `GET /api/runtime/openapi`

WebUI 后端会自动从 `config.toml` 读取 `[api].auth_key` 并注入 Header。

## 7. 故障排查

- 返回 `401 Unauthorized`：
  - `auth_key` 错误或请求头缺失。
- 返回 `503 Runtime API disabled`：
  - `[api].enabled = false`。
- WebUI 显示 `Runtime API unreachable`：
  - 主进程未启动或监听地址/端口配置不一致。
- `openapi.json` 返回 `404`：
  - `[api].openapi_enabled = false`。
