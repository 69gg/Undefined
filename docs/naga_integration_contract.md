# Undefined <-> NagaAgent Integration Contract

本文档给 NagaAgent 开发组使用，描述 Undefined 当前会提供的 Runtime API、Undefined 会调用的 Naga 接口，以及双方约定的鉴权方式。

## Shared Auth

- 所有双向 HTTP 请求都使用：

```http
Authorization: Bearer <config.[naga].api_key>
```

- `api_key` 是双方线下约定的共享密钥。
- Undefined 侧所有 Naga 相关接口都直接挂在 Runtime API 下。
- 这些端点只有在 `[api].enabled`、`[features].nagaagent_mode_enabled`、`[naga].enabled` 同时为 `true` 时才会注册。

## Undefined Provides

### 1. Bind Callback

`POST /api/v1/naga/bind/callback`

用途：

- Naga 端异步回调某个 `bind_uuid` 的最终结果
- 只有回调 `approved` 后，Undefined 才会真正激活绑定

请求体：

```json
{
  "bind_uuid": "unique-bind-uuid",
  "naga_id": "alice",
  "status": "approved",
  "delivery_signature": "opaque-signature-from-naga",
  "reason": ""
}
```

字段说明：

- `bind_uuid`: Undefined 发起绑定时生成的唯一请求号
- `naga_id`: 用户绑定的远端身份
- `status`: `approved` 或 `rejected`
- `delivery_signature`: 当 `status=approved` 时必填，后续所有消息发送/解绑都要带这个签名
- `reason`: 当 `status=rejected` 时可选，Undefined 会作为拒绝原因提示给用户

成功响应：

```json
{
  "ok": true,
  "status": "approved",
  "idempotent": false,
  "naga_id": "alice",
  "bind_uuid": "unique-bind-uuid"
}
```

### 2. Message Send

`POST /api/v1/naga/messages/send`

用途：

- Naga 端主动让 Undefined 向 QQ 发送文本或渲染消息

请求体：

```json
{
  "bind_uuid": "unique-bind-uuid",
  "naga_id": "alice",
  "delivery_signature": "opaque-signature-from-naga",
  "target": {
    "qq_id": 123456,
    "group_id": 654321,
    "mode": "both"
  },
  "message": {
    "format": "markdown",
    "content": "# hello"
  }
}
```

字段说明：

- `bind_uuid` + `naga_id` + `delivery_signature`：三者一起校验绑定身份
- `target.qq_id` / `target.group_id`: 目标参数必须显式提供，但只允许等于已绑定 QQ / 已绑定群
- `target.mode`: `private` / `group` / `both`
- `message.format`: `text` / `markdown` / `html`
- `message.content`: 实际消息内容

发送规则：

- Undefined 只允许投递到“绑定 QQ + 绑定群”
- 若 `mode` 包含 `group`，绑定群必须仍在 `config.[naga].allowed_groups`
- `markdown/html` 会按当前 Runtime API 的渲染逻辑先尝试转图片
- 若渲染失败，会回退为文本发送，并在响应中标记 `render_fallback=true`
- 当 `mode=both` 时，只要私聊或群聊至少有一个发送成功，接口仍返回 `200`；由 `sent_private` / `sent_group` 表示实际投递结果

审核规则：

- 发送前会做一次 AI 审核
- 若 `format=markdown/html`，不仅检查渲染后的语义，还会检查“未渲染直接发送时”的风险
- 明确命中以下风险时会拒发：
  - `pornography`
  - `politics_illegal`
  - `personal_privacy`
- 审核模型异常/超时时不拦截，但响应会返回 `moderation.status=error_allowed`

成功响应示例：

```json
{
  "ok": true,
  "naga_id": "alice",
  "bind_uuid": "unique-bind-uuid",
  "sent_private": true,
  "sent_group": true,
  "rendered": true,
  "render_fallback": false,
  "moderation": {
    "status": "passed",
    "blocked": false,
    "categories": [],
    "message": "ok",
    "model_name": "naga-moderation"
  }
}
```

拦截响应示例：

```json
{
  "ok": false,
  "error": "message blocked by moderation",
  "moderation": {
    "status": "blocked",
    "blocked": true,
    "categories": ["personal_privacy"],
    "message": "contains privacy leak",
    "model_name": "naga-moderation"
  }
}
```

### 3. Unbind

`POST /api/v1/naga/unbind`

用途：

- Naga 端主动要求 Undefined 吊销某个绑定

请求体：

```json
{
  "bind_uuid": "unique-bind-uuid",
  "naga_id": "alice",
  "delivery_signature": "opaque-signature-from-naga"
}
```

说明：

- 需要同时校验 `api_key`、`bind_uuid`、`naga_id`、`delivery_signature`
- 成功后该绑定立即失效

## Undefined Calls Naga

### 1. Bind Request

Undefined 在用户执行 `/naga bind <naga_id>` 后，会调用：

`POST {config.[naga].api_url}/api/integration/bind/request`

请求体：

```json
{
  "bind_uuid": "unique-bind-uuid",
  "naga_id": "alice",
  "request_context": {
    "naga_id": "alice",
    "sender_id": 123456,
    "group_id": 654321,
    "scope": "group",
    "bot_qq": 42,
    "group_name": "group-654321",
    "sender_nickname": "user-123456"
  }
}
```

说明：

- `bind_uuid` 是整个绑定流程的唯一关联键
- `request_context` 是 Undefined 能拿到的上下文摘要，字段可能按运行时情况增减
- Naga 端收到请求后，应在完成验证后调用 `POST /api/v1/naga/bind/callback`

### 2. Bind Revoke

Undefined 在本地 `/naga unbind` 成功后，会 best-effort 调用：

`POST {config.[naga].api_url}/api/integration/bind/revoke`

请求体：

```json
{
  "bind_uuid": "unique-bind-uuid",
  "naga_id": "alice"
}
```

说明：

- 这是同步吊销通知
- 即便这一步失败，Undefined 本地绑定也已经失效

## Error Handling

- `401 Unauthorized`: `Authorization` 缺失或 `api_key` 错误
- `POST /api/v1/naga/bind/callback`
  - `403`: `bind_uuid` / `delivery_signature` 不匹配
  - `404`: `pending` 不存在
  - `409`: 状态冲突，例如重复激活不同签名、请求已被其他结果终结
- `POST /api/v1/naga/messages/send`
  - `403`: 绑定不存在或已吊销、签名不匹配、目标不匹配、群不在白名单、审核拦截
  - `502`: 所有目标投递失败
- `POST /api/v1/naga/unbind`
  - `403`: `delivery_signature` 不匹配
  - `404`: 绑定不存在
  - `409`: 绑定代际不一致或其它状态冲突
- `502`: 目标投递失败

## Lifecycle Summary

1. 用户在白名单群执行 `/naga bind <naga_id>`
2. Undefined 生成 `bind_uuid` 并调用 Naga `bind/request`
3. Naga 完成验证后回调 Undefined `bind/callback`
4. 绑定生效后，Naga 可调用 `messages/send`
5. 任一方触发解绑后，Undefined 本地立刻吊销，并向对端同步
