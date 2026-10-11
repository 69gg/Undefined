# Undefined Chat

Undefined Chat 是 `apps/undefined-chat/` 下的原生优先 WebChat 客户端。它面向桌面端和 Android，直接连接 Runtime API，把会话、历史、任务、附件和事件都交给 Runtime 作为真源；Tauri 负责本地连接配置、API Key 保管、上传下载桥接、事件订阅和平台隔离能力。

## 当前功能矩阵

| 能力 | 当前状态 | 说明 |
|---|---|---|
| 会话管理 | 已实现 | 创建、删除、重命名、切换；重命名保留当前会话、草稿与移动端面板，未实现置顶会话 |
| 历史分页 | 已实现 | cursor-based 加载更早消息，prepend 后保持滚动锚点；超长历史采用窗口化渲染 |
| Markdown 渲染 | 已实现 | 表格、引用、列表、任务列表、链接、内联/块级代码 |
| 代码高亮 | 已实现 | highlight.js，多语言自动/显式高亮，支持复制 |
| 内联 HTML 渲染 | 已实现 | 正文 HTML 经 sanitize 后内联渲染，与 WebUI 基线对齐 |
| HTML 预览窗口 | 已实现 | 独立窗口/Android Activity，临时 file URL，预览窗口内可运行脚本；保留 `connect-src 'none'`、导航守卫、IPC 隔离、1 MB 限制和临时文件清理 |
| 附件上传/下载 | 已实现 | Tauri 流式上传、下载、预览；显示上传状态，不显示百分比进度 |
| 图片展示 | 已实现 | UID 附件图片经 Tauri 预览接口转 blob，支持内联、附件区和全屏查看 |
| 工具调用块 | 已实现 | 层级展示、状态、运行中实时计时（统一时钟）、阶段明细（stage detail）、与 WebUI 一致的输入/输出预览（JSON/Python 风格结构化、Markdown 输出、附件图片预览）；Agent 内正文与子调用按时间线顺序展示；历史回放支持 timeline/calls/events 多级回退 |
| 事件流 | 已实现 | SSE 优先，断开/错误时 JSON fallback（指数退避重连，活跃任务持续重试） |
| 命令面板 | 已实现 | `/` 候选、子命令、方向键、Tab/Enter 补全；空态反馈（加载中/无匹配/不可用）；窗口聚焦按 TTL 刷新命令列表 |
| 消息引用 | 已实现 | 引用 bot 消息、划词引用选中文本、发送引用、引用芯片跳转当前已加载源消息（不在当前页时自动加载一页更早历史，仍未命中需手动继续） |
| 自动滚动 | 已实现 | 智能跟随底部 + 设置面板开关，偏好持久化到 localStorage |
| 快捷键 | 已实现 | Ctrl/Cmd+N、Ctrl/Cmd+K、Ctrl/Cmd+/、Ctrl/Cmd+,、Escape |
| i18n | 已实现 | 中英双语运行时切换 + 语言切换 UI + 系统语言检测；UI 文案与逻辑层错误文案均走词典（store 存 key、UI `t()` 渲染） |
| 平台识别 | 已实现 | 经 Rust `get_platform_info` 判定真实平台（替代 UA 猜测）；移动布局结合真实平台 + 视口断点，桌面端按 `DesktopLayout` 包装 |
| 移动端适配 | 已实现 | 会话抽屉（role=dialog/aria-modal/Tab 焦点陷阱/焦点恢复）、软键盘避让、安全区（含横屏左右）、横屏/平板断点、44px 触控目标；仅 Android（非 iOS），后台 job 逐条补齐依赖 SSE 断线 fallback；逻辑由 jsdom 测试覆盖 |
| 移动端安全存储 | 已实现 | Android 使用 Keystore + AES-GCM，密钥在 AndroidKeyStore 不可导出，密文存 `MODE_PRIVATE` SharedPreferences；平台不可用时才允许显式不安全降级 |

## Undefined Chat vs WebUI WebChat

| 能力 | Undefined Chat | WebUI WebChat |
|---|---|---|
| 入口 | 独立 Tauri + React App | `uv run Undefined-webui` 内置聊天页 |
| 主要目标 | 原生聊天工作台，适合长期挂起、桌面/移动端使用 | 管理控制台内的聊天与调试入口 |
| 真源 | Runtime API | Runtime API，经 WebUI 后端代理 |
| 本地状态 | 连接设置、API Key 状态、当前选择、草稿、UI 游标 | 浏览器偏好和 UI 状态 |
| 事件续接 | SSE 优先，失败时 JSON polling fallback | JSON polling 为主，SSE 保留兼容 |
| 附件 | Tauri 以流式方式上传/下载 | WebUI 后端代理上传 |
| 密钥保管 | 桌面系统 keyring/Stronghold；Android Keystore + AES-GCM | WebUI 后端注入 Runtime auth key |
| HTML 渲染 | 正文 sanitize 内联 + Tauri 独立窗口/Activity 隔离运行 | 正文 sanitize 内联 + 浏览器 iframe sandbox |

## Runtime 是唯一真源

Undefined Chat 不持久化权威聊天数据。以下内容都以 Runtime 返回为准：

- `GET /api/v1/chat/conversations`
- `GET /api/v1/chat/history`
- `GET /api/v1/chat/jobs/active`
- `GET /api/v1/chat/jobs/{job_id}/events`
- Runtime 附件 API 返回的附件元数据、下载 URL 和预览 URL

本地只保存 UI 相关状态，例如当前会话、草稿、事件游标、窗口布局、连接档案和是否允许不安全存储降级。刷新、重启或换端之后，客户端必须重新从 Runtime 恢复会话和任务状态。

连接到不同 Runtime 时，会清理旧实例的草稿、附件 UID、消息引用、历史、任务和图片预览缓存，并丢弃旧实例迟到的请求或订阅通知，避免相同会话 ID 造成跨实例误发送。同一 Runtime 的重连及 Android 恢复保留编辑状态和 UI 偏好；自动滚动、平台与布局偏好在切换实例时也保留。

发送请求会立即清空编辑器并显示乐观用户消息。发送失败时移除该乐观消息，仅恢复请求后未再编辑的原始草稿、附件或引用；新输入和主动清空保留，各字段独立判断，不覆盖用户准备的下一条消息。

## 连接与事件

Runtime 请求必须由 Tauri command 拼接到已配置 origin 下，避免 React 传入任意 URL 后绕过目标主机限制。React 不直接持有 API Key；受保护请求由 Rust 侧注入 `X-Undefined-API-Key`。

保存连接配置时会暂停 Runtime 请求及任务订阅。URL 保存后，密钥或降级确认失败会恢复先前 URL（首次配置则清除新 URL）；客户端显示原生端实际保存的目标，并保持不可发送的配置界面，要求重新输入密钥后连接。恢复 URL 失败时也保持此限制；原生配置无法读取时保留最后确认的目标并继续禁用请求。不会用旧会话界面操作新目标，或假定失败的密钥写入一定没有副作用。

事件策略：

- 默认使用 SSE 订阅 job events。
- SSE error/closed 或原生订阅建立失败时使用 `job_id + seq` 调用 JSON events fallback 补齐遗漏事件；消息已成功创建 job 后，订阅失败不会撤回用户消息或恢复已发送草稿。
- Runtime 任务快照包含 `current_timeline`：完整的顶层消息、已结束和运行中的调用树，以及 Agent 内消息与子调用的顺序。客户端接受此快照时同时推进到 `last_seq`，SSE 与 JSON 只追加后续序号，避免正文丢失或重复。
- 旧 Runtime 缺少 `current_timeline` 时，客户端保留快照的完整正文前缀，JSON fallback 先续接事件以保留已有调用树；重放缓冲缺失消息时按权威正文恢复。同一任务恢复时，推进游标前复用 JSON 回放补齐后台工具开始、结束和 Agent 阶段变化，即使正文没有改变；回放失败保留旧游标供 SSE 继续恢复。旧服务无法仅凭正文恢复已超出事件缓冲的完整 Agent 嵌套顺序。
- 重叠 JSON 请求按 job 身份和请求代次校验；已结束、已被替换的 job 或落后于已消费事件游标的回包会被忽略，避免迟到响应覆盖下一轮任务或回退回复内容。
- 取消请求错误和 SSE 的连接状态通知同样只作用于对应的活跃 job，旧任务的迟到通知不会改写新任务的错误或连接状态。
- `done` / `error` / `cancelled` 事件到达后，客户端继续保留当前会话的 job 和发送锁，通过 JSON polling 等待 `history_finalized=true`，确认历史落盘后再刷新历史并清理订阅。
- 历史分页的 `before` / `next_before` 是非负数值索引；React 与 Tauri command 使用同一数值契约，首屏不传 `before`。
- Android 回到前台时执行 `store.bootstrap()`，刷新配置、会话、当前历史页和 active jobs；每个任务接受完整快照及其游标后重新建立事件订阅。已从 active 列表消失的本地任务还会补刷所属会话的权威历史，包括非当前会话；已删除会话不再请求。请求途中已消费更高序号时保留更新的本地状态。
- 同一 Runtime 重建订阅时保留已开始的终态历史刷新；切换 Runtime 或暂停保存连接配置时，旧请求响应仍会被丢弃。

## 安全存储

API Key 不应暴露给 React 状态树或日志。Tauri 负责保存、读取和删除密钥：

- macOS 使用系统钥匙串，Windows 使用系统凭据存储。
- Linux 依赖 Secret Service/keyring；无可用 keyring 时，必须让用户显式确认后才允许降级到本地文件。
- Android 通过生成工程注入的 `SecretPlugin` 使用 Android Keystore + AES-GCM 保存 API Key：密钥在 AndroidKeyStore 中生成且不可导出，加密后的密文存放在 `MODE_PRIVATE` 的 SharedPreferences 中。
- 降级模式只适合本机开发或受控环境。

> iOS 仅 `keyring` 库的 `apple-native` backend 在代码层兼容 Keychain，未纳入构建/发布（无 iOS 工程/CI/真机路径），不是受支持的发布平台。

## 附件与大文件上传

附件上传由 Tauri 从文件句柄流式读取并转发到 Runtime，React 只持有文件选择结果和上传状态。桌面路径和 `file://` URL 会做 regular file 校验；Android `content://` URI 交给 `tauri-plugin-fs` 打开，不强制使用本地 `metadata().is_file()` 判定。

保存连接配置时，未完成的附件上传会转为失败状态；恢复连接后可移除并重新选择文件。同一 Runtime 已上传成功的附件保留，旧上传的成功或失败响应不会恢复已移除条目。普通同地址重连或 Android 恢复不暂停配置，正在上传的附件仍可正常结算；切换 Runtime 继续清理旧附件。

下载和预览同样通过 Tauri 受控命令处理。下载以原子创建方式占用文件名，同名文件依次添加数字后缀，并发下载也不会覆盖已有文件；可用候选名耗尽时明确报错。图片附件通过 `AttachmentImage` 或附件预览按钮调用 `previewAttachment`，Rust 端带 auth 拉取附件字节，再转为 `Blob` URL 渲染；全屏预览走应用内 `ImageViewerModal`，关闭时释放临时 URL。

历史时间线未接入全局图片查看回调时使用本地 `ImagePreview`。可从图片通过 Enter / Space 打开，焦点进入关闭按钮，Tab / Shift+Tab 保持在预览内；Escape、点击遮罩或关闭按钮均可关闭，焦点恢复到触发图片。

## HTML 渲染与预览

HTML 采用与 WebUI 基线对齐的双层策略：

- **正文内联渲染**：消息正文中的 HTML 经 sanitize 后内联渲染，去除可执行/危险内容后嵌入消息流。
- **独立预览窗口**：HTML/HTM 代码块可在独立预览窗口/Activity 中打开，预览窗口内允许运行脚本，以获得与 WebUI 一致的预览体验。

独立预览窗口在放开脚本执行的同时，仍保留以下安全边界：

- 运行时写入 `html-preview-*.html` 临时文件，并通过 `Url::from_file_path` 打开初始 `file://` URL。
- `connect-src 'none'` 阻断预览内的网络请求；表单提交、插件对象等仍受限。
- 导航守卫只允许初始 URL 和 `about:blank`，禁止外部导航。
- 预览窗口与主应用 IPC 隔离，不暴露主应用的 Tauri command。
- 标题会转义；标题 + HTML 总大小限制为 1 MB。
- 关闭窗口会删除对应临时文件；下次打开前只清理陈旧残留，避免删掉仍打开窗口的 backing file。

详情见 [HTML 预览文档](../apps/undefined-chat/docs/html-preview.md)。

## 移动端与 Android

移动端实现包括：

- 会话列表抽屉、遮罩、Escape 关闭、ARIA 状态和焦点恢复。
- `visualViewport` 驱动的 `--keyboard-inset`，用于输入区软键盘避让。
- 安全区 `env(safe-area-inset-*)` 和移动端 44px 触控目标。
- Android 生命周期使用 Tauri `tauri://suspended` / `tauri://resumed`。卸载或重新注册时也会清理尚未完成的异步监听，已经释放的监听回调不会再次触发重连。

真实设备或模拟器 smoke 建议覆盖：

- `content://` 上传：相册、Downloads、云盘 provider。
- 软键盘、安全区、横竖屏切换和 Tab/触控顺序。
- 后台运行中 job 恢复。
- Android Keystore 保存、重启后读取、删除和降级提示。

## 测试与发布

`apps/undefined-chat/package.json` 的 `npm run check` 包含：

- `npm run lint`
- `npm run typecheck`
- `npm run test:unit`
- `npm run test:e2e`（Vitest + jsdom integration tests）
- `npm run test:build`（独立 Node 测试：临时生产构建、chunk 体积与导入图、全语言高亮一致性）
- `npm run tauri:fmt:check`
- `npm run tauri:check`
- `npm run tauri:test`

生产构建将应用、React、其他依赖与高亮模块分开；全部高亮语言仍同步注册并保持自动检测。分包控制单个 chunk 的大小并细化缓存粒度，总下载体积基本不变；独立 gzip 压缩会因减少字典复用而增加压缩体积。构建回归执行实际输出的高亮模块，核对语言顺序、逐语言结果与自动检测，并检查默认体积门槛和导入图无环。

jsdom integration tests 不等同于真实 Tauri/Android E2E。发布前仍应执行 Android smoke checklist 和必要的桌面 Tauri smoke。

版本必须与 `pyproject.toml` 主版本一致。`scripts/bump_version.py <version>` 会同步更新 Chat/Console 的 package、Tauri 配置和 lock 文件。Android release job 会先运行 `npm run tauri:android:init`，为 Undefined Chat 注入 `HtmlPreviewActivity` / `SecretPlugin` 并用 `tauri:android:prepare:check` 校验生成工程。
