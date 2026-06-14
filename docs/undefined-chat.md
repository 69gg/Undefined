# Undefined Chat

Undefined Chat 是 `apps/undefined-chat/` 下的原生优先 WebChat 客户端。它面向桌面端和 Android，直接连接 Runtime API，把会话、历史、任务、附件和事件都交给 Runtime 作为真源；Tauri 负责本地连接配置、API Key 保管、上传下载桥接、事件订阅和平台隔离能力。

## 当前功能矩阵

| 能力 | 当前状态 | 说明 |
|---|---|---|
| 会话管理 | 已实现 | 创建、删除、重命名、切换；未实现置顶会话 |
| 历史分页 | 已实现 | cursor-based 加载更早消息，prepend 后保持滚动锚点；超长历史采用窗口化渲染 |
| Markdown 渲染 | 已实现 | 表格、引用、列表、任务列表、链接、内联/块级代码 |
| 代码高亮 | 已实现 | highlight.js，多语言自动/显式高亮，支持复制 |
| HTML 预览 | 已实现 | 独立窗口/Android Activity，临时 file URL，严格 CSP，1 MB 限制和临时文件清理 |
| 附件上传/下载 | 已实现 | Tauri 流式上传、下载、预览；显示上传状态，不显示百分比进度 |
| 图片展示 | 已实现 | UID 附件图片经 Tauri 预览接口转 blob，支持内联、附件区和全屏查看 |
| 工具调用块 | 已实现 | 层级展示、状态、耗时、结果预览 |
| 事件流 | 已实现 | SSE 优先，断开/错误时 JSON fallback |
| 命令面板 | 已实现 | `/` 候选、子命令、方向键、Tab/Enter 补全 |
| 消息引用 | 已实现 | 引用 bot 消息、发送引用、引用芯片跳转当前已加载源消息 |
| 快捷键 | 已实现 | Ctrl/Cmd+N、Ctrl/Cmd+K、Ctrl/Cmd+/、Ctrl/Cmd+,、Escape |
| i18n | 部分实现 | 有中英文词典和测试，但 App 主要界面仍以中文静态文案为主，没有语言切换 UI |
| 移动端适配 | 部分实现 | 会话抽屉、ARIA 状态、焦点恢复、软键盘 CSS 变量和 44px 触控目标；仍需真机验证 |
| 移动端安全存储 | 未完整 | Android/iOS 当前不支持系统 keyring，只能显式不安全降级 |

## Undefined Chat vs WebUI WebChat

| 能力 | Undefined Chat | WebUI WebChat |
|---|---|---|
| 入口 | 独立 Tauri + React App | `uv run Undefined-webui` 内置聊天页 |
| 主要目标 | 原生聊天工作台，适合长期挂起、桌面/移动端使用 | 管理控制台内的聊天与调试入口 |
| 真源 | Runtime API | Runtime API，经 WebUI 后端代理 |
| 本地状态 | 连接设置、API Key 状态、当前选择、草稿、UI 游标 | 浏览器偏好和 UI 状态 |
| 事件续接 | SSE 优先，失败时 JSON polling fallback | JSON polling 为主，SSE 保留兼容 |
| 附件 | Tauri 以流式方式上传/下载 | WebUI 后端代理上传 |
| 密钥保管 | 桌面系统 keyring/Stronghold；移动端需显式不安全降级 | WebUI 后端注入 Runtime auth key |
| HTML 预览 | Tauri 独立窗口/Activity + CSP | 浏览器 iframe sandbox + WebUI CSP |

## Runtime 是唯一真源

Undefined Chat 不持久化权威聊天数据。以下内容都以 Runtime 返回为准：

- `GET /api/v1/chat/conversations`
- `GET /api/v1/chat/history`
- `GET /api/v1/chat/jobs/active`
- `GET /api/v1/chat/jobs/{job_id}/events`
- Runtime 附件 API 返回的附件元数据、下载 URL 和预览 URL

本地只保存 UI 相关状态，例如当前会话、草稿、事件游标、窗口布局、连接档案和是否允许不安全存储降级。刷新、重启或换端之后，客户端必须重新从 Runtime 恢复会话和任务状态。

## 连接与事件

Runtime 请求必须由 Tauri command 拼接到已配置 origin 下，避免 React 传入任意 URL 后绕过目标主机限制。React 不直接持有 API Key；受保护请求由 Rust 侧注入 `X-Undefined-API-Key`。

事件策略：

- 默认使用 SSE 订阅 job events。
- SSE error/closed 时使用 `job_id + seq` 调用 JSON events fallback 补齐遗漏事件。
- Android 回到前台时执行 `store.bootstrap()`，刷新配置、会话、当前历史页和 active jobs，并重新建立事件订阅。
- 当前没有公开的 store 方法在 resume 时逐 job 主动补齐；这部分仍依赖 SSE 断线 fallback。

## 安全存储

API Key 不应暴露给 React 状态树或日志。Tauri 负责保存、读取和删除密钥：

- macOS 使用系统钥匙串，Windows 使用系统凭据存储。
- Linux 依赖 Secret Service/keyring；无可用 keyring 时，必须让用户显式确认后才允许降级到本地文件。
- Android/iOS 当前不支持系统 keyring。移动端保存 API Key 需要用户显式接受不安全降级，或后续接入平台安全存储。
- 降级模式只适合本机开发或受控环境。

## 附件与大文件上传

附件上传由 Tauri 从文件句柄流式读取并转发到 Runtime，React 只持有文件选择结果和上传状态。桌面路径和 `file://` URL 会做 regular file 校验；Android `content://` URI 交给 `tauri-plugin-fs` 打开，不强制使用本地 `metadata().is_file()` 判定。

下载和预览同样通过 Tauri 受控命令处理。图片附件通过 `AttachmentImage` 调用 `previewAttachment`，Rust 端带 auth 拉取附件字节，再转为 `Blob` URL 渲染。

## HTML Preview

聊天中的 HTML 预览使用独立预览窗口/Activity：

- 运行时写入 `html-preview-*.html` 临时文件，并通过 `Url::from_file_path` 打开初始 `file://` URL。
- CSP 禁止脚本、网络请求、表单提交、插件对象和外部导航。
- 导航守卫只允许初始 URL 和 `about:blank`。
- 标题会转义，HTML 内容按原样渲染；预览是隔离容器，不是内容净化器。
- 标题 + HTML 总大小限制为 1 MB。
- 关闭窗口和下次打开前会清理预览临时文件。

详情见 [HTML 预览文档](../apps/undefined-chat/docs/html-preview.md)。

## 移动端与 Android

移动端实现包括：

- 会话列表抽屉、遮罩、Escape 关闭、ARIA 状态和焦点恢复。
- `visualViewport` 驱动的 `--keyboard-inset`，用于输入区软键盘避让。
- 安全区 `env(safe-area-inset-*)` 和移动端 44px 触控目标。
- Android 生命周期使用 Tauri `tauri://suspended` / `tauri://resumed`。

仍需真实设备验证：

- `content://` 上传：相册、Downloads、云盘 provider。
- 软键盘、安全区、横竖屏切换和 Tab/触控顺序。
- 后台运行中 job 恢复。
- Android 安全存储降级提示和重启后读取。

## 测试与发布

`apps/undefined-chat/package.json` 的 `npm run check` 包含：

- `npm run lint`
- `npm run typecheck`
- `npm run test:unit`
- `npm run test:e2e`（Vitest + jsdom integration tests）
- `npm run tauri:fmt:check`
- `npm run tauri:check`
- `npm run tauri:test`

jsdom integration tests 不等同于真实 Tauri/Android E2E。发布前仍应执行 Android smoke checklist 和必要的桌面 Tauri smoke。

版本必须与 `pyproject.toml` 主版本一致。`scripts/bump_version.py <version>` 会同步更新 Chat/Console 的 package、Tauri 配置和 lock 文件。Android release job 会先运行 `npm run tauri:android:init`，为 Undefined Chat 注入 `HtmlPreviewActivity` 并用 `tauri:android:prepare:check` 校验生成工程。
