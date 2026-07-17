# 微信 ClawBot / iLink 私聊接入

Undefined 可以通过微信 ClawBot 的 iLink 接口接收和发送微信私聊消息。该接入不依赖 OneBot 在线状态，也不需要安装 OpenClaw 或微信插件；Undefined 主进程直接管理 iLink 帐号的登录、长轮询和发送生命周期。

> 这是基于公开可获取包体与网络协议行为实现的非官方兼容层，不是腾讯提供的稳定 SDK。上游协议、风控或可用范围可能变化。首次启用前请自行确认帐号和服务条款风险，并先使用非关键帐号验证。

## 身份与路由

每个微信帐号绑定一个“逻辑 QQ 号”。逻辑身份决定权限、私聊历史、认知记忆和模型偏好；物理通道只决定回复从 QQ 还是微信发出。

例如，微信帐号绑定逻辑 QQ `12345678` 后：

- AI 输入中的 `sender_id` 仍为 `12345678`。
- 微信入站消息带有 `channel="wechat"`、`address="wechat:12345678"` 和“微信私聊”位置。
- 历史与 QQ 私聊 `12345678` 共用逻辑会话，但每条记录保留 transport 元数据。
- QQ 与微信的短窗口消息合并桶分开，避免两个物理通道互相抢占回复。

显式投递统一使用规范地址：

| 地址 | 含义 |
|---|---|
| `qq:12345678` | QQ 私聊 |
| `wechat:12345678` | 绑定到该逻辑 QQ 的微信私聊 |
| `group:87654321` | QQ 群聊 |

`messages.send_message`、`messages.send_private_message` 和定时任务均支持 `address`。旧的 `target_type + target_id`、`user_id`、`group_id` 参数继续兼容，但无法表达微信物理通道，新增配置应优先使用规范地址。`messages.send_message` 的 `address` 与 `target_type` / `target_id` 互斥；调度任务同时携带规范地址和旧目标时，也必须指向同一规范会话。

## 配置

先在 `config.toml` 中启用接入，再重启 Bot 主进程：

```toml
[weixin]
enabled = true
state_dir = "data/weixin"
long_poll_timeout_seconds = 35.0
stale_token_pause_seconds = 3600.0
retry_delay_seconds = 2.0
failure_backoff_seconds = 30.0
failures_before_backoff = 3
media_max_size_mb = 100
login_session_ttl_seconds = 300.0
privileged_confirmation_ttl_seconds = 300.0
pending_max_records = 100
audit_max_records = 1000
```

| 字段 | 作用 |
|---|---|
| `enabled` | 总开关；为 `false` 时不建立 iLink 网络连接 |
| `state_dir` | 帐号凭据、游标、隔离记录和审计记录目录 |
| `long_poll_timeout_seconds` | 单次消息长轮询超时 |
| `stale_token_pause_seconds` | 上游提示 token 过期时的暂停时间 |
| `retry_delay_seconds` | 普通失败后的重试间隔 |
| `failure_backoff_seconds` | 连续失败达到阈值后的退避时间 |
| `failures_before_backoff` | 进入长退避前允许的连续失败次数 |
| `media_max_size_mb` | 单个入站或出站媒体的大小上限 |
| `login_session_ttl_seconds` | 二维码登录会话有效期 |
| `privileged_confirmation_ttl_seconds` | 管理员身份二次确认 token 有效期 |
| `pending_max_records` | 未知来源隔离记录上限 |
| `audit_max_records` | 帐号管理审计记录上限 |

`state_dir/bindings.json` 和 `state_dir/runtime.json` 包含敏感登录状态，在 POSIX 系统上会设置为 `0600`。不要提交、共享或放入 Web 静态目录；备份时按凭据文件处理。

## 管理页绑定

1. 启动 `Undefined-webui`，并从 WebUI 启动 Bot。
2. 打开“微信接入”页，确认 Runtime 显示运行中。
3. 点击“绑定帐号”，填写本地别名和要继承的逻辑 QQ 号。
4. 使用微信扫描页面生成的二维码；上游要求验证码时在同一对话框提交。
5. 绑定成功后确认帐号显示在线，再发送一条测试私聊。

别名只用于本机管理和日志，不会发送给微信。一个逻辑 QQ 在全局最多绑定一个微信帐号，同一 ClawBot 帐号也不能重复绑定。

若目标 QQ 是管理员或超级管理员，第一次提交只返回权限继承警告和短时确认 token；必须再次明确确认才会创建二维码登录。确认、登录、启停、改绑和解绑都会写入审计记录。

## 隔离与访问控制

iLink 帐号只接受登录结果声明的那个私聊来源。若收到帐号 ID 或来源 ID 不匹配的消息，Undefined 会在 AI、命令、管线和历史处理之前隔离：

- 不保存消息正文或附件。
- 不调用 AI 或命令。
- 不发送自动回复。
- 只保存帐号别名、来源 ID、原因、首次/最后出现时间和计数。

管理页可以查看并忽略隔离记录。已绑定消息仍遵循 `[access]` 的私聊名单；绑定微信不会绕过访问控制。绑定管理员逻辑 QQ 会完整继承其权限，因此必须保护 WebUI 和 Runtime API 鉴权密钥。

## 媒体与限制

当前支持：

- 入站：文本、图片、文件、视频、语音转写；原始 SILK 语音作为附件保留。
- 引用入站：微信引用的旧文本或媒体会作为独立的只读 `reply_context` 保存并提供给 AI，不会与用户当前正文混在一起，也不会单独触发命令或自动管线。若 iLink 只返回引用 `message_id` 而省略摘要，Undefined 会先按同一 `wechat:<逻辑QQ号>` 路由精确查询历史。机器人出站消息在本地只拥有 `client_id`、而微信引用返回服务端数字 `msg_id` 时，会再利用引用 item 的创建时间和同路由发送时间恢复；旧历史中同一秒存在多个机器人片段时，会明确作为同一发送时刻的候选上下文提供，不冒充精确片段。目标不在当前路由、时间无法可靠匹配或已超出历史保留范围时不会跨会话查找。
- 出站：支持 Markdown 渲染的文本、图片、文件、视频、原生语音、同一物理微信会话内的 `reply_to` 引用和输入中状态；超过 4000 字符的文本会自动分片，文本与媒体混合消息会在全量本地预检后按原始片段顺序投递。
- 明确不支持：跨微信帐号或跨 QQ/微信通道引用、群聊。

发送引用时，`reply_to` 必须是当前 `wechat:<逻辑QQ号>` 历史中可见的 `message_id`。Undefined 会先验证物理路由，再把经过清理的旧消息摘要作为 iLink 原生引用发送；若上游明确拒绝原生引用，则自动改为 Markdown 引用。网络超时、会话暂停等不确定失败不会触发降级重发，以免产生重复消息。

微信文本中的 `<`、`>`、`&` 等特殊符号和 `<attachment uid="..."/>` 附件标签应原样发送，不使用 HTML/XML 实体。微信没有 QQ 合并转发的等价合同。对当前微信私聊发送合并转发时，Undefined 会按节点顺序降级为普通文本和媒体。包含本地 CQ 图片、文件、视频或音频的消息会走统一附件发送层，媒体本地路径不会作为正文发给用户。

Bot 层通过 `messages.send_voice(uid, address?)` 显式选择“作为语音发送”。普通 `<attachment uid="file_xxx"/>` 始终保留原始文件语义，即使扩展名是 `.wav`；`CQ:record`、`CQ:audio` 和内部明确标记为 voice 的媒体回调则发送原生语音。QQ 侧继续转换为 `CQ:record`，微信侧先用 FFmpeg 归一化为 24 kHz、16-bit、单声道 PCM，再由 `silk-python` 编码为 Tencent SILK。部署机必须能从 `PATH` 找到 `ffmpeg`；缺失、音频无效或超出 `[weixin].media_max_size_mb` 时会在任何消息段发出前失败，不会自动改成文件。

AI 接收到的当前微信消息、微信历史消息、历史查询工具结果和引用正文仍使用 XML 外层结构，但正文放在标准 CDATA 字面量中；因此 `<`、`>`、`&` 等字符会以用户原始输入直接出现，用户输入中的 `]]>` 也会拆成连续 CDATA 段后无损还原。CDATA 内容是只读的用户文本，不做实体编码或解码：若用户实际输入 `&lt;tag&gt;`，AI 看到的仍是这串字面字符，而不是 `<tag>`。运行时还会在每个微信输入批次前注入投递约束，并要求 AI 在调用发送工具前检查 `message`；工具参数是 JSON 字符串，必须使用原始字符，不能把模型自行产生的 `&lt;`、`&gt;`、`&amp;` 或错误的 `&it;` 发给用户。只有用户明确要求讨论或展示实体拼写本身时才保留实体文本。

帐号连接在 SDK 已覆盖的长轮询网络重试之外，还会在启动失败、入站回调异常或轮询意外退出时按 `[weixin]` 的 `retry_delay_seconds`、`failures_before_backoff` 和 `failure_backoff_seconds` 重建客户端。二维码过期后原会话继续保留，可直接刷新或取消；开始同一别名或逻辑 QQ 的新登录时会先清理已过期会话，避免遗留冲突。

## Runtime API

所有端点使用 Runtime API 的 `X-Undefined-API-Key` 鉴权。WebUI 通过 Management 后端代理调用，不把 API Key 暴露给浏览器。

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/api/v1/weixin` | 服务和帐号状态 |
| `POST` | `/api/v1/weixin/login` | 创建二维码登录会话 |
| `GET` | `/api/v1/weixin/login/{session_id}` | 查询扫码状态 |
| `GET` | `/api/v1/weixin/login/{session_id}/qr.png` | 获取无缓存二维码 PNG |
| `POST` | `/api/v1/weixin/login/{session_id}/refresh` | 刷新二维码 |
| `POST` | `/api/v1/weixin/login/{session_id}/verify` | 提交验证码 |
| `DELETE` | `/api/v1/weixin/login/{session_id}` | 取消登录会话 |
| `PATCH` | `/api/v1/weixin/accounts/{alias}` | 启停帐号或改绑逻辑 QQ |
| `DELETE` | `/api/v1/weixin/accounts/{alias}` | 解绑并删除本地凭据 |
| `GET` | `/api/v1/weixin/pending` | 查看隔离来源 |
| `DELETE` | `/api/v1/weixin/pending/{record_id}` | 忽略隔离记录 |
| `GET` | `/api/v1/weixin/audit` | 查看帐号管理审计 |

二维码响应使用 `Cache-Control: no-store`。API 状态和公开帐号结构不会返回 bot token、account ID、peer ID 或二维码原始登录载荷。

## 可复用 Python SDK

底层协议客户端已独立为 MIT 项目 [weixin-ilink-client](https://github.com/69gg/weixin-ilink-client)，包名同为 `weixin-ilink-client`。Undefined 仅负责身份绑定、访问控制、历史、附件、调度和管理 API；二维码登录、协议传输、长轮询、媒体传输和状态存储接口由 SDK 提供。

SDK 作者信息为 Null `<pylindex@qq.com>`，支持 Python 3.11 及以上。引用消息从 `0.1.1` 开始受支持，Tencent SILK 出站语音从 `0.1.2` 开始受支持；Undefined 固定使用兼容的 `0.1.x` 版本范围，避免未经验证的协议破坏性升级自动进入运行环境。

## 实机验证清单

仓库测试不会发起真实二维码登录或连接微信。首次实机验证建议逐项确认：

1. 二维码刷新、取消、过期和验证码状态均能收敛。
2. 文本入站只回复到 `wechat:<逻辑QQ号>`，不会误发到 QQ。
3. 同一逻辑 QQ 的历史和认知记忆可见，但微信与 QQ 的并发回复路由不串线。
4. 未知来源只增加隔离计数，历史中没有正文。
5. 图片、文件、视频、语音转写和 WAV 原生语音分别测试大小上限、FFmpeg 缺失及失败提示；确认普通 WAV 附件仍可作为文件下载。
6. 引用一条文本和一条媒体消息，确认 AI 能看到只读引用；再让 AI 使用当前外层 `message_id` 原生引用回复。
7. 停用、重启、改绑和解绑后的客户端任务与凭据状态符合预期。
8. 管理员身份必须出现二次确认，审计记录包含对应操作。

若上游协议返回未知状态或字段，先停用该帐号并保留脱敏日志；不要反复扫码或高频重试，以免放大帐号风控风险。
