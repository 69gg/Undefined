# Undefined Chat 独立 App 设计规格

日期：2026-06-07
状态：设计已确认，等待实现计划

## 目标

新增一个独立跨平台聊天客户端 `Undefined Chat`，目录为 `apps/undefined-chat`。它只做 WebChat 体验，不承载 WebUI 管理功能，也不复用 `apps/undefined-console` 作为入口。客户端直连远端 Runtime API，产品形态覆盖 Windows、macOS、Linux 和 Android。

核心原则：

- Runtime API 是唯一后端真源。
- 客户端是 thin client，只采集输入、调用 API、展示 Runtime 返回的数据。
- 客户端不维护聊天历史真源，不做本地 job 队列，不判断命令权限，不生成最终附件/引用表达。
- 换客户端、换设备或重新打开 app 后，连接同一个 Runtime 时应看到一致的会话、历史、运行态和事件续接结果。

## 非目标

- 首期不做浏览器 Web 版。
- 首期不做多连接档案。
- 首期不做桌面多窗口并排聊天，但架构保留以后扩展单会话窗口的可能性。
- 首期不承诺 Android 进程被系统杀死后仍能实时通知；重新打开后恢复状态是硬要求。

## 技术路线

采用 Tauri v2 + React + TypeScript，新建 `apps/undefined-chat`。

客户端保存一个 Runtime 连接：

- `runtime_url`
- `X-Undefined-API-Key`

API Key 首期使用 `tauri-plugin-stronghold` 加密保存。Stronghold vault 的密码派生策略必须在 Tauri 原生层实现，不把 vault password 硬编码进前端 bundle。若目标平台或运行环境无法使用 Stronghold，必须让用户明确确认后才允许降级到普通本地保存，并在设置页持续显示风险提示。连接 URL、主题、语言、草稿、自动滚动等 UI 偏好保存在普通本地配置中。

Runtime 请求通过 Tauri 原生层集中封装：React 调用本地命令，Tauri 根据当前单连接配置拼接 URL、添加 API Key、执行 HTTP 请求。这样可以把请求权限限制在用户配置的 Runtime origin 上，避免前端散落拼接认证头和过宽 HTTP allowlist。

## Runtime API 契约

现有 WebChat 能力应提升为 Runtime 正式契约。现有会话、历史、job、事件和命令接口继续保留，并补齐以下能力。

### 结构化发送

`POST /api/v1/chat/jobs` 支持结构化 payload。客户端只提交用户输入结构，Runtime 负责生成最终历史记录和 AI 输入。

请求形态：

```json
{
  "conversation_id": "conversation-id",
  "message": {
    "text": "用户输入",
    "attachment_ids": ["attachment-id"],
    "references": [
      {
        "kind": "message",
        "source_message_id": "message-id",
        "selected_text": "用户选中的文字"
      }
    ]
  }
}
```

Runtime 负责：

- 验证会话存在。
- 验证附件 ID 属于当前 WebChat 附件作用域。
- 将引用规范化为历史和 AI 可见的引用表达。
- 注册附件并生成 AI 可见的附件 XML。
- 写入用户消息历史。
- 创建并返回 job 快照。

为了支持引用，历史记录需要返回稳定的 `message_id`。客户端不应依赖数组下标作为长期引用目标。

### 附件 API

新增 Runtime 原生附件接口，替代当前只存在于 WebUI Management 代理层的 `/api/runtime/chat/files`。

新增端点：

- `POST /api/v1/chat/attachments`：multipart 上传文件，返回 Runtime 生成的 attachment id、文件名、大小、媒体类型、渲染提示。
- `GET /api/v1/chat/attachments/{attachment_id}`：下载文件。
- `GET /api/v1/chat/attachments/{attachment_id}/preview`：返回预览资源，例如图片缩略图；没有预览资源时返回明确的 404/415 错误。

Runtime 必须通过能力端点或上传端点错误响应暴露当前最大上传大小，例如 `max_upload_size_bytes`。该值来自 Runtime 配置，客户端不得硬编码上传上限。客户端可以在待发送区显示本地临时预览，但 canonical 附件表达只来自 Runtime 返回的 attachment id/schema。

Tauri 原生层上传文件时必须使用 streaming 方式把本地文件 pipe 到 HTTP 请求，不允许为了上传而把大文件一次性读入 JS Blob、base64 字符串或 IPC payload。客户端在上传前按 Runtime 暴露的大小上限做本地拦截，并正确展示 Runtime 的 `413`、超时和连接中断错误。

### 按会话并发 job

WebChat job 管理从全局互斥改为按 `conversation_id` 互斥：

- 不同会话可以同时运行 job。
- 同一会话已有 job 运行或收尾落盘时，再次发送返回 `409`。
- 删除或清空会话只阻塞目标会话；其他会话不受影响。
- `GET /api/v1/chat/jobs/active?conversation_id=<id>` 返回目标会话的 active job。
- 不传 `conversation_id` 时返回 `jobs` 数组；为了兼容旧前端，可同时保留 `job` 字段为第一个 active job 或 `null`，但 Undefined Chat 只依赖 `jobs`。

事件流首选 Server-Sent Events。`GET /api/v1/chat/jobs/{job_id}/events` 在 `Accept: text/event-stream` 时返回 SSE，事件 `id` 使用 Runtime 的递增 `seq`；客户端重连时使用 `Last-Event-ID` 或显式 `after=<seq>` 续接。JSON 事件查询仅作为后台、恢复、兼容或 SSE 不可用时的 fallback。客户端只渲染 Runtime 返回的事件和快照，不自行推断最终状态。

### 历史与事件 schema

历史接口返回足够展示的结构化数据：

- `message_id`
- `role`
- `content`
- `attachments`
- `webchat.timeline`
- `webchat.calls`
- `webchat.events`
- `duration_ms`
- render hints

事件接口返回：

- `stage`
- `message`
- `message_delta`，当 Runtime 支持正文增量时使用；客户端必须能同时处理增量和最终 `message`。
- `tool_start` / `tool_end`
- `agent_start` / `agent_end`
- `requires_action`，为未来 Human-in-the-loop 手动干预预留。
- `done`
- `error`
- 当前工具/Agent 快照
- Runtime 计算的耗时字段

客户端不从正文中反推工具状态，不根据本地计时覆盖 Runtime 快照。

### Human-in-the-loop 扩展点

首期不实现高危操作审批工作流，但 Runtime job schema 预留 `waiting_input` 状态和 `requires_action` 事件。未来如果工具或 Agent 需要用户授权、补充参数或确认高危操作，Runtime 负责生成结构化 action payload、暂停目标会话 job，并保持该会话输入区锁定；其他会话继续运行。客户端只渲染 Runtime 返回的 action，并把用户选择提交回 Runtime 的后续端点，不在本地保存未提交的业务状态。

## 客户端数据流

启动或恢复：

1. 读取本地单连接配置。
2. 查询 Runtime 健康状态。
3. 拉取会话列表。
4. 拉取 active jobs。
5. 加载当前会话历史。
6. 对运行中 job 使用 SSE 订阅事件，并用 `job_id + seq` 续接。

发送：

1. 用户输入文本、选择附件或引用。
2. 文件先上传到 Runtime 附件接口。
3. 客户端提交结构化 message payload。
4. Runtime 返回 job 快照。
5. 目标会话输入区锁定，其他会话不锁定。
6. 客户端订阅 SSE 事件并渲染 Runtime 状态；SSE 不可用时降级为 JSON 事件查询。

断线恢复：

1. UI 显示连接异常或重连中。
2. 恢复后重新拉会话、active jobs、当前历史。
3. 对仍运行的 job 从已知 seq 通过 SSE 或 JSON fallback 续接。
4. 如果 Runtime 重启导致 job 消失，客户端刷新历史并结束本地运行态展示。

## UI 与交互

信息架构采用 Chat-first。

桌面端：

- 左侧会话列表，中央聊天流。
- 聊天流占据主视图。
- 输入区固定底部，包含引用、附件预览、斜杠命令补全和发送。
- 工具/Agent 调用在 AI 气泡内显示摘要、状态和耗时。
- 工具详情、Agent 调用树、附件详情通过按需侧栏或抽屉展开，不默认抢占聊天区。
- HTML 运行预览打开独立桌面窗口。

Android：

- 默认进入当前聊天页。
- 会话列表、工具详情、附件详情、HTML 预览、设置作为原生页面、抽屉或底部导航目标。
- HTML 运行预览进入独立页面，不使用悬浮窗口。
- 多会话运行态在会话列表可见。

主题与语言：

- 支持亮色、暗色、跟随系统。
- 默认中文。
- 首期支持中英双语，i18n 结构支持后续扩展其他语言。

## 消息能力

首期支持完整消息能力：

- 文本
- 图片
- 普通文件
- 引用 AI 消息、选中文字、HTML 片段
- Markdown 渲染
- 安全 HTML 渲染
- 代码块高亮、复制、折叠
- HTML 运行预览
- 图片预览
- 文件下载卡片

斜杠命令补全完整支持 `GET /api/v1/commands?scope=webui`：

- 命令名
- 别名
- 子命令
- 帮助块
- 键盘导航
- Runtime 返回的可用性状态

客户端只展示命令数据，不自行判断权限。

## 前端模块

模块边界：

- `runtime-client`：Runtime HTTP、认证、错误类型、重试封装。
- `chat-store`：当前 UI 选择、active job 快照、事件游标、草稿和偏好；不保存历史真源。
- `conversation-list`：会话列表和每个会话的运行态。
- `message-timeline`：按 Runtime history/timeline schema 渲染消息、附件和调用摘要。
- `message-composer`：文本输入、附件选择、引用选择、斜杠命令补全，提交结构化 payload。
- `rendering`：Markdown、安全 HTML、代码块、预览、复制、折叠。
- `native`：Tauri 设置存储、通知、托盘、窗口、文件选择和下载保存。

## 原生能力

Tauri 层负责：

- 单连接配置本地保存。
- API Key Stronghold 加密保存；不可用时经用户确认后降级。
- 系统通知。
- 桌面托盘和隐藏窗口常驻。
- Android 后台尽力续接。
- 文件选择。
- 下载保存。
- 桌面 HTML 预览窗口。
- Android HTML 预览页面。

通知只基于 Runtime 事件和 job 快照触发：

- job 完成
- job 失败
- 连接异常
- 重连恢复

## 错误处理

错误状态必须映射为明确 UI：

- Runtime 不可达。
- API Key 缺失或无效。
- 401 / 403。
- 会话不存在。
- 同会话 job 运行中返回 409。
- 上传文件超限。
- 附件不存在。
- job 取消。
- job 失败。
- Runtime 重启导致 active job 丢失。

客户端不猜测最终结果。所有最终状态以 Runtime 返回为准。

## 安全边界

- API Key 首选 Stronghold 加密保存；只有在 Stronghold 不可用且用户明确确认时才允许普通本地保存，设置页必须持续提示降级风险。
- 聊天内 HTML 经过白名单净化。
- HTML 运行预览隔离执行，不暴露 API Key，不开放 Tauri IPC，不允许访问本地文件或 app 能力。
- HTML 预览窗口或页面必须注入严格 CSP meta。默认策略禁止外部网络、禁止表单提交、禁止对象加载、禁止父页面访问；允许的脚本、样式和资源范围必须最小化，并明确禁止 `unsafe-eval`。
- 附件下载文件名和路径必须清洗，禁止路径穿越。
- 危险协议、事件属性和危险样式必须被剥离。
- Runtime 预览字段会脱敏，但不作为权限边界；工具实现仍应避免输出完整凭证。

## 测试要求

后端 pytest 覆盖：

- Runtime 结构化发送 payload。
- Runtime 附件上传、下载、预览。
- 上传大小上限、413、超时和 streaming 上传路径。
- 附件注册和历史返回 schema。
- 引用归一化。
- 按会话并发 job。
- 同会话 409。
- SSE 事件流、`Last-Event-ID` / `seq` 续接和 JSON fallback。
- `waiting_input` / `requires_action` schema 预留。
- 删除和清空会话阻塞。
- history/event schema。
- OpenAPI 文档同步。
- 旧 WebUI WebChat 兼容。

前端测试覆盖：

- Runtime client。
- 启动恢复和断线恢复。
- SSE 事件合并、断线续接、JSON fallback 和快照渲染。
- 会话列表运行态。
- 同会话输入区锁定。
- 命令补全。
- 附件上传 payload。
- 文件大小拦截、上传超时和 streaming 上传错误展示。
- 引用 payload。
- Markdown/HTML/代码块渲染。
- HTML 预览 CSP 和 IPC 隔离。
- 工具/Agent 调用树展示。
- 通知触发条件。

质量门禁：

- `uv run pytest tests/`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy .`
- `uv build --wheel`
- `apps/undefined-chat` 的 npm lint/typecheck/test。
- `apps/undefined-chat` 的 Tauri cargo fmt/check。
- 桌面亮/暗主题截图验收。
- Android 聊天页、会话列表、详情页、设置页、HTML 预览页截图验收。

## 文档要求

需要同步更新：

- `docs/openapi.md`
- `docs/webui-guide.md`
- 新增 `docs/undefined-chat.md`
- `docs/app.md`
- `README.md`
- `apps/undefined-chat/README.md`
- `scripts/README.md`

文档必须说明：

- Undefined Chat 和 WebUI WebChat 都是 Runtime WebChat 客户端。
- Runtime 是唯一真源。
- Undefined Chat 直连 Runtime API。
- API Key 首期使用 Stronghold 加密保存；降级保存需要用户确认并提示风险。
- SSE 是运行中 job 的首选事件通道，JSON 查询是恢复和兼容 fallback。
- Android 后台通知能力是尽力而为，重新打开恢复是硬保证。

## CI 与发版

CI 增加独立 `undefined-chat-quality-check`：

- npm lint。
- npm typecheck。
- React 测试。
- Tauri cargo fmt/check。

Release workflow 增加 Undefined Chat 打包：

- verify chat app。
- Windows installer。
- Linux AppImage/deb。
- macOS dmg。
- Android 多 ABI release APK。

产物命名需要与 Console 区分，例如：

- `Undefined-Chat-vX.Y.Z-linux-x64.AppImage`
- `Undefined-Chat-vX.Y.Z-linux-x64.deb`
- `Undefined-Chat-vX.Y.Z-windows-x64-setup.exe`
- `Undefined-Chat-vX.Y.Z-windows-x64.msi`
- `Undefined-Chat-vX.Y.Z-macos-x64.dmg`
- `Undefined-Chat-vX.Y.Z-macos-arm64.dmg`
- `Undefined-Chat-vX.Y.Z-android-arm64-v8a-release.apk`

## 版本同步

`pyproject.toml` 仍是主版本真源。`scripts/bump_version.py` 必须同步更新 Undefined Chat：

- `apps/undefined-chat/package.json`
- `apps/undefined-chat/package-lock.json`
- `apps/undefined-chat/src-tauri/Cargo.toml`
- `apps/undefined-chat/src-tauri/tauri.conf.json`
- `apps/undefined-chat/src-tauri/Cargo.lock`

`scripts/release_notes.py validate` 也必须把 Undefined Chat 加入版本一致性校验。`scripts/README.md` 同步更新校验范围。

## 验收标准

- 同一个 Runtime 可被多个 Undefined Chat 客户端连接，所有会话、历史、active jobs 和事件续接保持一致。
- 多个会话可同时运行 job。
- 同一会话运行中不能再次发送。
- 客户端关闭、刷新、换设备后重新连接，能从 Runtime 恢复状态。
- 完整消息能力可用。
- 桌面和 Android 都符合原生导航习惯。
- WebUI WebChat 不回退。
- CI 和 release 均包含 Undefined Chat。
