# Management API 与远程管理

本文档说明 `Undefined-webui` 暴露的 **Management API**。它负责控制面能力：登录、token 刷新、配置编辑、日志读取、Bot 启停、bootstrap 探针，以及对主进程 Runtime API 的代理访问。

> 简单理解：
>
> - **Management API**：面向 WebUI / 桌面端 / Android App 的管理入口
> - **Runtime API**：面向机器人主进程运行态与集成能力
>
> 配置缺失、配置损坏、主进程未启动时，优先依赖 Management API 完成恢复。

## 1. 推荐入口

推荐先运行：

```bash
uv run Undefined-webui
```

然后：

1. 在浏览器中打开 WebUI
2. 登录并修改密码（首次）
3. 编辑配置、保存并校验
4. 直接在控制台启动 Bot
5. 如需远程管理，再让桌面端或 Android App 连接同一个 Management API 地址

> WebUI 各页面的功能和操作详见 [WebUI 使用指南](webui-guide.md)。

## 2. 鉴权模型

Management API 兼容两套鉴权：

- **Cookie Session**：浏览器 WebUI 继续沿用
- **Bearer Token**：桌面端 / Android App 推荐使用

### 登录

- `POST /api/v1/management/auth/login`

请求体：

```json
{
  "password": "your-webui-password"
}
```

成功后返回：

```json
{
  "success": true,
  "access_token": "...",
  "refresh_token": "...",
  "expires_in": 900,
  "refresh_expires_in": 28800,
  "access_token_expires_at": 1741420800000
}
```

同时浏览器会收到兼容旧逻辑的 session cookie。

### 刷新 token

- `POST /api/v1/management/auth/refresh`

请求体：

```json
{
  "refresh_token": "..."
}
```

### 查询会话

- `GET /api/v1/management/auth/session`

返回当前是否已认证、是否仍在使用默认密码、配置文件是否存在，以及控制面的 capabilities。

### 登出

- `POST /api/v1/management/auth/logout`

会撤销当前 bearer token / refresh token / cookie session。

## 3. Bootstrap 与 Capabilities 探针

### Bootstrap probe

- `GET /api/v1/management/probes/bootstrap`

用于描述“当前实例是否已经进入可修复/可启动状态”。典型字段：

- `config_exists`
- `toml_valid`
- `config_valid`
- `validation_error`
- `using_default_password`
- `runtime_enabled`
- `runtime_reachable`
- `advice`

适合 WebUI 和 App 在首页直接判断：

- 是否需要先补配置
- 是否需要先改密码
- 是否只是 Runtime 未启动
- 是否可以直接点“启动 Bot”

### Capabilities probe

- `GET /api/v1/management/probes/capabilities`

用于告诉客户端当前控制面支持哪些能力，例如：

- token 鉴权
- bootstrap probe
- runtime proxy
- config read/write/validate
- logs read/stream
- bot start/stop/update-restart
- 桌面端 / Android 客户端支持

## 4. 配置相关接口

- `GET /api/v1/management/config`
- `POST /api/v1/management/config`
- `GET /api/v1/management/config/summary`
- `POST /api/v1/management/config/patch`
- `POST /api/v1/management/config/validate`
- `POST /api/v1/management/config/sync-template`

说明：

- `config`：读取/整体保存源文本
- `summary`：读取结构化配置摘要与注释映射
- `patch`：按路径增量修改
- `validate`：先做 TOML 语法校验，再做严格配置校验
- `sync-template`：把 `config.toml.example` 中新增字段/注释同步到当前配置

## 5. 日志、系统与 Bot 控制

### 日志

- `GET /api/v1/management/logs`
- `GET /api/v1/management/logs/files`
- `GET /api/v1/management/logs/stream`

### 系统信息

- `GET /api/v1/management/system`

### Bot 控制

- `GET /api/v1/management/status`
- `POST /api/v1/management/bot/start`
- `POST /api/v1/management/bot/stop`
- `POST /api/v1/management/update-restart`

## 6. Runtime 代理

Management API 会把运行态相关能力统一代理到主进程 Runtime API，便于客户端只连接一个入口：

- `GET /api/v1/management/runtime/meta`
- `GET /api/v1/management/runtime/openapi`
- `GET /api/v1/management/runtime/probes/internal`
- `GET /api/v1/management/runtime/probes/external`
- `GET /api/v1/management/runtime/memory`
- `GET /api/v1/management/runtime/cognitive/events`
- `GET /api/v1/management/runtime/cognitive/profiles`
- `GET /api/v1/management/runtime/cognitive/profile/{entity_type}/{entity_id}`
- `GET /api/v1/management/runtime/commands`
- `GET /api/v1/management/runtime/commands/{command_name}`
- `GET /api/v1/management/runtime/chat/conversations`
- `POST /api/v1/management/runtime/chat/conversations`
- `PATCH /api/v1/management/runtime/chat/conversations/{conversation_id}`
- `DELETE /api/v1/management/runtime/chat/conversations/{conversation_id}`
- `POST /api/v1/management/runtime/chat`
- `GET /api/v1/management/runtime/chat/history`
- `DELETE /api/v1/management/runtime/chat/history`
- `POST /api/v1/management/runtime/chat/jobs`
- `POST /api/v1/management/runtime/chat/files`
- `GET /api/v1/management/runtime/chat/jobs/active`
- `GET /api/v1/management/runtime/chat/jobs/{job_id}`
- `GET /api/v1/management/runtime/chat/jobs/{job_id}/events`
- `POST /api/v1/management/runtime/chat/jobs/{job_id}/cancel`

所有 Runtime 代理端点都会先校验 Management session / access token，再由 WebUI 后端注入 `X-Undefined-API-Key`；浏览器不会接触 Runtime `[api].auth_key`。

### `runtime/commands`

代理 Runtime 斜杠命令 REST 资源，供 WebChat `/` 补全面板和管理端命令浏览使用。

- 参数：
  - `scope`：默认 `webui`；也可传 `private` / `group`。
  - `q`、`include_hidden`、`include_unavailable`、`sender_id`、`user_id`、`group_id`：原样透传给 Runtime。
- 校验：
  - Management 登录态或 access token 必须有效。
  - 后端注入 `X-Undefined-API-Key`。
- 响应：
  - `200`：命令、别名、子命令、用法、权限和当前 scope 可用性。
  - Runtime 鉴权或配置错误会透传对应错误状态。

```http
GET /api/v1/management/runtime/commands?scope=webui&q=help
```

### `runtime/chat/conversations`

管理 WebChat 多对话，支持查询、新建、重命名和删除。

- 参数 / Body：
  - `GET` 无必填参数。
  - `POST` 可传 `{"title":"..."}`。
  - `PATCH` 传 `{"title":"..."}`。
  - `DELETE` 使用路径参数 `conversation_id`。
- 校验：
  - 删除会话时 Runtime 会检查是否存在运行中或收尾落盘中的 WebChat job。
- 响应：
  - `200` / `201`：会话列表或会话对象。
  - `404`：会话不存在。
  - `409`：仍有 WebChat job 阻塞会话删除。

```json
{
  "conversation": {
    "id": "legacy-system-42",
    "title": "新对话",
    "virtual_user_id": 42
  }
}
```

### `runtime/chat`、`runtime/chat/history`、`runtime/chat/jobs`、`runtime/chat/jobs/active`

代理 WebChat 发送、历史分页、后台 job 创建和 active job 查询；`conversation_id` 会在 body 或 query 中原样透传。

- 参数 / Body：
  - `conversation_id`：可选；不传时使用 Runtime 默认兼容会话。
  - `POST runtime/chat`：`message` 必填，`stream` 可选。
  - `GET runtime/chat/history`：`limit`、`before`、`conversation_id`。
  - `DELETE runtime/chat/history`：`conversation_id`。
  - `POST runtime/chat/jobs`：`message` 必填，`conversation_id` 可选。
  - `GET runtime/chat/jobs/active`：`conversation_id` 可选。
- 校验：
  - Runtime 会检查 `conversation_id` 是否存在。
  - 删除历史时，如果仍有运行中或收尾落盘中的 job，会透传 `409`。
- 响应：
  - `200` / `202`：聊天结果、历史页、job 快照或 active job。
  - `404`：会话不存在。
  - `409`：job 正在运行或历史尚未完成落盘。
- 元数据语义：
  - `webchat.duration_ms`、`webchat.events`、`webchat.timeline`、`current_tool_calls`、`stage` / `agent_stage` 是 **display-only**，用于刷新后恢复工具 / Agent 展示块、阶段和耗时。
  - 这些 WebChat 展示元数据不是 **AI-context**，不会作为后续 AI 对话上下文注入。
  - 工具 / Agent 输入输出预览由 Runtime 统一脱敏和截断。

```json
{
  "message": "你好",
  "conversation_id": "legacy-system-42"
}
```

### `runtime/chat/files`

缓存 WebChat 待发送文件，前端随后把返回的 `id` 合并为 `CQ:file` 随当前消息提交。

- 参数 / Body：
  - `multipart/form-data` 字段 `file` 必填。
- 校验：
  - Management 登录态或 access token 必须有效。
  - Runtime / WebUI 文件大小限制会返回 `413`。
- 响应：
  - `200`：`{ "id": "...", "name": "...", "size": 123 }`。
  - `400`：缺少 `file` 字段或 multipart body 无效。
  - `413`：文件超过限制。

```http
POST /api/v1/management/runtime/chat/files
Content-Type: multipart/form-data
```

```json
{ "id": "abc123", "name": "report.pdf", "size": 2048 }
```

前端合并为：

```text
CQ:file,id=abc123,name=report.pdf,size=2048
```

### `runtime/chat/jobs/{job_id}/events`

按 `conversation_id + job_id + seq` 续接 WebChat job 事件，支持 JSON 增量查询和兼容 SSE。

- 参数：
  - `conversation_id`：可选；传入时必须与 job 所属会话一致。
  - `after`：返回大于该 `seq` 的事件。
  - `format=json`：显式 JSON 查询。
  - `Accept: text/event-stream`：透传 Runtime WebChat SSE。
- 校验：
  - `conversation_id` 不一致时返回 `404`，避免跨会话误续接。
- 响应：
  - 默认 JSON：持久事件、当前顶层 `stage` 快照、当前 `agent_stage` 快照、`current_tool_calls` 和耗时字段。
  - SSE：事件帧和 keep-alive 由 Runtime 透传。

```json
{
  "job": {
    "job_id": "9c1...",
    "status": "running",
    "current_stage": "waiting_tools",
    "current_tool_calls": []
  },
  "after": 4,
  "last_seq": 5,
  "events": [
    { "seq": 5, "event": "stage", "payload": { "stage": "waiting_tools" } }
  ]
}
```

```text
id: 5
event: stage
data: {"stage":"waiting_tools"}
```

除此之外，Management API 还额外代理了表情包库管理接口：

- `GET /api/v1/management/memes`
- `GET /api/v1/management/memes/stats`
- `GET /api/v1/management/memes/{uid}`
- `GET /api/v1/management/memes/{uid}/blob`
- `GET /api/v1/management/memes/{uid}/preview`
- `PATCH /api/v1/management/memes/{uid}`
- `DELETE /api/v1/management/memes/{uid}`
- `POST /api/v1/management/memes/{uid}/reanalyze`
- `POST /api/v1/management/memes/{uid}/reindex`

说明：
- `GET /api/v1/management/memes` 支持：
  - `q`：列表关键词过滤
  - `query_mode`：`keyword` / `semantic` / `hybrid`
  - `keyword_query`：单独的关键词查询词（可选）
  - `semantic_query`：单独的语义查询词（可选）
  - `top_k`：检索候选数；带查询模式时优先用于检索
  - `enabled`：`true/false`
  - `animated`：`true/false`
  - `pinned`：`true/false`
  - `sort`：`updated_at` / `use_count` / `created_at`
  - `page` / `page_size`
- 管理页的“重跑分析”会重新走两阶段 LLM 管线：
  1. 判定是否表情包
  2. 生成纯文本描述与标签
- 管理页的“重建索引”只重建向量索引，不重新跑判定。

## 7. 适用场景

推荐使用 Management API 的场景：

- 首次部署，`config.toml` 还没补齐
- 配置损坏，主进程起不来
- 想远程修改配置、看日志、重启 Bot
- 想让桌面端 / Android App 共用统一管理入口

如果你只关心主进程的运行态能力和第三方集成，可以直接看 [Runtime API / OpenAPI 文档](openapi.md)。
