# Undefined Chat

Undefined Chat 是 `apps/undefined-chat/` 下的原生优先 WebChat 客户端。它面向桌面端和 Android，直接连接 Runtime API，把会话、历史、任务、附件和事件都交给 Runtime 作为真源；Tauri 只负责本地连接配置、API Key 保管、上传下载桥接、事件订阅和平台隔离能力。

## 设计重写说明

Undefined Chat 在 v3.5.2 版本完成全面重写，采用莫兰迪橙色系（Morandi Orange）设计系统，与 WebUI 保持视觉一致性。重写包括：

- **统一配色**：采用莫兰迪橙色系，支持浅色/深色模式，与 WebUI 视觉语言统一
- **功能对等**：100% 移植 WebUI webchat 的所有核心功能（详见下方功能对比表）
- **原生优化**：针对桌面和 Android 平台优化交互、生命周期管理和安全存储
- **代码重构**：重写所有组件、样式和状态管理，提升可维护性和性能

## WebUI 功能对等

| 功能 | WebUI WebChat | Undefined Chat | 平台差异说明 |
|------|---------------|----------------|------------|
| **会话管理** | ✅ | ✅ | 完整支持创建、删除、切换、置顶 |
| **消息历史分页** | ✅ | ✅ | 均使用 cursor-based 无限滚动 |
| **Markdown 渲染** | ✅ | ✅ | 表格、引用、列表、任务列表 |
| **代码高亮** | ✅ | ✅ | 均使用 highlight.js |
| **图片内联** | ✅ | ✅ | < 12MB 自动内联，> 12MB 预览链接 |
| **附件上传/下载** | ✅ | ✅ | Chat 使用 Tauri 流式传输 |
| **工具调用块** | ✅ | ✅ | 层级展示、折叠/展开 |
| **事件流** | ✅ | ✅ | Chat 使用 SSE 优先 + JSON fallback |
| **命令面板** | ✅ | ✅ | 斜杠命令补全 + 子命令提示，方向键导航自动滚动、Tab/Enter 补全 |
| **消息引用** | ✅ | ✅ | 引用芯片、跳转源消息 |
| **HTML 预览** | ✅ | ✅ | 桌面：独立窗口，Android：Activity |
| **图片查看器** | ✅ | ✅ | 全屏查看、缩放、旋转 |
| **代码块折叠** | ✅ | ✅ | > 8 行自动折叠 |
| **自动滚动** | ✅ | ✅ | 可开关、智能暂停 |
| **国际化** | ✅ | ✅ | 中英文界面 |
| **快捷键** | ❌ | ✅ | 仅桌面端，浏览器限制 |
| **安全存储** | N/A | ✅ | 系统凭据管理器 |

### 近期体验优化（对齐 WebUI）

在视觉与交互细节上进一步对齐 WebUI webchat：

- **命令系统**：命令面板由后端 `/api/v1/commands` 完整命令元数据驱动（命令、子命令、用法、示例、别名）。输入 `/` 即时展示候选；输入 `/命令 ` 或回车选中带子命令的主命令后立即进入子命令模式并展示候选；命令无子命令时显示帮助卡片。方向键导航越界自动滚动，`Tab`/`Enter` 补全当前项，`Esc` 关闭。解析、匹配、补全抽象为 `message-composer/command-context.ts` 纯函数，1:1 对齐 WebUI 逻辑并附单元测试。
- **图片查看器**：点击消息图片弹出全屏 lightbox（毛玻璃背景、可选标题、`Esc`/点击背景关闭），关闭按钮适配刘海安全区。
- **消息自动滚动**：流式回复增长、工具块/事件更新、图片异步撑高时持续贴底（双 rAF 等布局完成，确保彻底到底）；用户上滚查看历史时智能暂停，回到底部恢复；切换会话回到底部。
- **对话区去除 emoji**：消息头像改为圆圈内首字母（机器人 `U` / 用户 `你`），欢迎页快捷卡片改用描边 SVG 图标，整体观感更克制。
- **移动端响应式**：侧栏抽屉随窗口宽度实时切换（`useMediaQuery` + `matchMedia`，响应缩放/旋屏），输入区与 lightbox 适配 `env(safe-area-inset-*)` 安全区。
- **会话管理**：会话项悬停显示删除按钮，删除走二次确认弹窗（`ConfirmDialog`）；新建会话期间按钮显示"正在新建…"加载态；点击会话且历史尚未加载时显示加载态而非欢迎页（区分"加载中"与"空会话"）。
- **图片统一走 UID**：webchat 命令输出中的内联图片（如 `/stats` 的 base64 图表、`file://` 渲染图）在输出环节即注册为附件、替换为 `<attachment uid/>`，客户端按 UID 经 `/api/v1/chat/attachments/{uid}/preview` 拉取渲染。历史不再存储 base64（避免整段 base64 进入后续 LLM prompt 导致 token 超限），Runtime API 也不再返回 base64；图片统一 `loading="lazy"` + `decoding="async"` 懒加载。QQ 投递路径不受影响。后端 `register_message_attachments` 经 `segment_text` 重建消息文本，已彻底消除 `[CQ:image]`/`[CQ:file]` 等 CQ 码（注册成功 → `<attachment uid/>`，失败 → `[图片: …]` 可读占位），故客户端只需识别 UID 附件标签；早期从 webui 通用渲染函数移植的 CQ 解析逻辑（`resolveCQImageUrl` 等）作为死代码已移除。
- **附件 URL 跨源解析**：Undefined Chat 作为独立 Tauri 应用连接远程 `runtimeUrl`，与 Runtime **不同源**。后端返回的 `preview_url`/`download_url` 为相对路径（如 `/api/v1/chat/attachments/{uid}/preview`），若直接渲染会被解析到 `tauri://localhost` 而加载失败。客户端在渲染前统一经 `resolveAttachmentUrl`（`rendering/AttachmentProcessor.ts`）补上 `runtimeUrl` 前缀，覆盖正文 `<attachment uid/>` 图片、附件区缩略图与点击查看的全屏大图；`http(s)`/`data:`/`blob:` 等绝对地址原样透传，避免重复前缀。

## 配色系统

Undefined Chat 采用与 WebUI 相同的莫兰迪橙色系，确保跨平台视觉体验一致：

### 浅色模式
- **主色**：`#d97757`（莫兰迪橙）
- **悬停色**：`#c56545`（深橙）
- **背景**：`#f9f5f1`（暖白）
- **面板**：`#ffffff`（白色）
- **边框**：`#e6e0d8`（暖灰边框）
- **文本**：`#3d3935`（深棕灰）

### 深色模式
- **主色**：`#d97757`（莫兰迪橙）
- **悬停色**：`#c56545`（深橙）
- **背景**：`#0f1112`（深黑）
- **面板**：`#171c1f`（深灰）
- **边框**：`#2b3439`（深灰边框）
- **文本**：`#f4efe7`（暖白文本）

## Undefined Chat vs WebUI WebChat

| 能力 | Undefined Chat | WebUI WebChat |
|---|---|---|
| 入口 | 独立 Tauri + React App | `uv run Undefined-webui` 内置聊天页 |
| 主要目标 | 原生聊天工作台，适合长期挂起、桌面/移动端使用 | 管理控制台内的聊天与调试入口 |
| 真源 | Runtime API | Runtime API，经 WebUI 后端代理 |
| 本地状态 | 只保存连接设置、API Key 状态、当前选择、草稿和 UI 游标 | 浏览器本地偏好和 UI 状态 |
| 会话/历史 | 从 Runtime 拉取，不在本地复制为权威数据 | 从 Runtime 拉取，不在浏览器复制为权威数据 |
| 事件续接 | SSE 优先，失败或平台不稳定时使用 JSON polling fallback | JSON polling 为主，SSE 保留兼容 |
| 附件 | Tauri 以流式方式上传/下载，避免把大文件完整塞进前端内存 | WebUI 后端代理上传，再交给 Runtime |
| 密钥保管 | 系统 keyring / Stronghold，Linux 可显式降级到不安全本地存储 | WebUI 登录态，Runtime `auth_key` 只在后端注入 |
| HTML 预览 | Tauri 隔离窗口/页面，执行环境受专用 CSP 约束 | 浏览器 iframe sandbox + WebUI CSP |
| Android | 需要处理前后台、页面恢复、事件重连和上传不中断 | 依赖移动浏览器或 WebView 行为 |

## Runtime 是唯一真源

Undefined Chat 不持久化权威聊天数据。以下内容都以 Runtime 返回为准：

- `GET /api/v1/chat/conversations` 的会话列表
- `GET /api/v1/chat/history` 的历史页
- `GET /api/v1/chat/jobs/active` 的运行中任务
- `GET /api/v1/chat/jobs/{job_id}/events` 的事件序列
- Runtime 附件 API 返回的附件元数据、下载 URL 和预览 URL

本地只允许保存 UI 相关状态，例如当前选中的会话、每个会话的未发送草稿、事件游标、窗口布局、连接档案和是否允许不安全存储降级。刷新、重启或换端之后，客户端必须重新从 Runtime 恢复会话和任务状态。

## 连接与事件

连接配置包含 Runtime origin 和 API Key 状态。Runtime 请求必须由 Tauri 命令拼接到已配置 origin 下，避免 React 传入任意 URL 后绕过目标主机限制。

事件策略：

- 默认使用 SSE 订阅 job events，保持低延迟。
- SSE 断开、平台暂停、网络切换或 Android 生命周期恢复后，使用 `job_id + seq` 调用 JSON events fallback 补齐遗漏事件。
- JSON fallback 不改变 Runtime 合同，只是同一事件流的拉取方式。
- 客户端渲染时应按 Runtime `seq` 去重，不能把本地收到顺序当作权威顺序。

## 安全存储

API Key 不应暴露给 React 状态树或日志。Tauri 负责保存、读取和删除密钥：

- 首选系统安全存储或 Stronghold。
- macOS 使用系统钥匙串，Windows 使用系统凭据存储。
- Linux 依赖 Secret Service/keyring；无可用 keyring 时，必须让用户显式确认后才允许降级。
- 降级模式只适合本机开发或受控环境，文档和 UI 都应标明风险。

## 附件与大文件上传

Undefined Chat 的附件上传由 Tauri 从文件句柄流式读取并转发到 Runtime，React 只持有文件选择结果和上传状态。这样可以避免大文件占满前端内存，也能让桌面端和 Android 在上传过程中继续响应 UI。

客户端应先读取 Runtime 能力端点提供的上传大小限制；超过限制时在本地阻止或让 Runtime 返回明确错误。下载和预览同样通过 Tauri 受控命令处理，不能让 React 任意读取本地路径。

## HTML Preview CSP

聊天中的 HTML 预览需要隔离执行。Undefined Chat 使用独立预览页面/窗口承载 HTML，预览环境应具备单独 CSP：

- 禁止访问主应用 DOM、Tauri IPC 和本地文件系统。
- 禁止脚本执行、`unsafe-eval` 和外部网络连接。
- 关闭预览或切换会话时销毁对应执行上下文。

普通消息渲染仍应先净化 HTML；只有“运行/预览 HTML”动作才进入隔离预览环境。

## Android 生命周期

Android 上需要按生命周期处理连接和任务恢复：

- App 进入后台后，SSE 可能被系统暂停或断开。
- 回到前台时先刷新 Runtime health、会话列表、当前 history 页和 active jobs。
- 对仍在运行的 job，以最后已处理 `seq` 调用 JSON fallback 补齐事件，再尝试恢复 SSE。
- 上传大文件时应提示用户保持 App 前台；如系统中断上传，客户端应展示失败状态并允许重新上传。
- 本地草稿在前后台切换和进程重建后可恢复，但不能替代 Runtime 历史。

## 版本、CI 与 Release

Undefined Chat 的版本必须与 `pyproject.toml` 主版本一致。`scripts/bump_version.py <version>` 会同步更新：

- `apps/undefined-chat/package.json`
- `apps/undefined-chat/package-lock.json`
- `apps/undefined-chat/src-tauri/Cargo.toml`
- `apps/undefined-chat/src-tauri/tauri.conf.json`
- `apps/undefined-chat/src-tauri/Cargo.lock`

Release 校验由 `scripts/release_notes.py validate --tag vX.Y.Z` 执行，会同时检查 Console 与 Chat 的 manifest 和 lock 文件。CI 会对 `apps/undefined-chat` 执行 `npm run check`；正式发布时产物使用 `Undefined-Chat-*` 前缀，与 `Undefined-Console-*` 区分。

Android release job 会先运行 `npm run tauri:android:init`。对 Undefined Chat，该命令会在 Tauri 生成 `src-tauri/gen/android` 后执行 `scripts/prepare_tauri_android.py`，注入 HTML preview 专用的 `HtmlPreviewActivity` 并用 `tauri:android:prepare:check` 校验生成工程。
