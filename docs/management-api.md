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
- `POST /api/v1/management/runtime/chat`
- `GET /api/v1/management/runtime/chat/history`

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
