# Undefined Chat

Undefined Chat 是 `apps/undefined-chat/` 下的 Tauri v2 + React 19 原生聊天客户端。它直接连接 Runtime API；会话、历史、任务、附件和事件以 Runtime 为真源，本地只保存连接配置、API Key 状态、草稿和 UI 游标。

完整产品说明见 [docs/undefined-chat.md](../../docs/undefined-chat.md)。

## 当前能力

- 会话管理：创建、删除、重命名、切换会话。当前没有置顶字段/API。
- 消息历史：初始加载、cursor-based 加载更早消息、滚动锚点保持和长历史窗口化渲染。
- 消息渲染：Markdown、表格、任务列表、引用块、代码高亮、代码块复制；正文 HTML 经 sanitize 内联渲染，HTML 代码块可在独立预览窗口中运行。
- 附件：系统文件选择器、上传状态队列、Tauri 流式上传、下载和预览。当前显示上传中/成功/失败状态，不显示百分比进度。
- 图片：正文 `<attachment uid/>` 内联图、附件缩略图、blob 缓存、全屏查看、缩放、旋转和可滚动查看区域。
- 命令：斜杠命令、子命令提示、方向键导航、Tab/Enter 补全；空态反馈（加载中/无匹配/不可用）；窗口聚焦按 TTL 刷新命令列表。
- 引用：引用 bot 消息、划词引用选中文本、发送引用、引用芯片跳转当前已加载源消息；源消息不在当前页时会自动加载一页更早历史，仍未命中需手动继续加载更早历史。
- 工具调用块：层级展示、状态、运行中实时计时、阶段明细（stage detail）、JSON 结果结构化；历史回放支持 timeline/calls/events 多级回退。
- 自动滚动：智能跟随底部，可在设置面板开关，偏好持久化到 localStorage。
- 事件：SSE 优先，断开时 JSON fallback（指数退避重连，活跃任务持续重试）。
- 快捷键：Ctrl/Cmd+N 新会话，Ctrl/Cmd+K 聚焦输入并打开命令模式，Ctrl/Cmd+/ 切换侧栏，Ctrl/Cmd+, 打开设置，Escape 关闭当前弹层/抽屉。
- i18n：中英双语运行时切换，提供语言切换 UI，并按系统语言自动检测默认语言。

## 平台状态

桌面端：

- HTML 渲染对齐 WebUI 基线：正文 HTML 经 sanitize 内联渲染；HTML 代码块在独立预览窗口/Activity 中打开，预览窗口内允许运行脚本，同时保留 `connect-src 'none'`、导航守卫、IPC 隔离、临时 file URL、1 MB 限制和临时文件清理等安全边界。
- API Key 优先保存在系统凭据管理器/Stronghold。macOS 使用 Keychain，Windows 使用系统凭据存储，Linux 依赖 Secret Service；不可用时必须显式确认不安全文件降级。
- Tauri fs/http 插件仅由 Rust commands 内部使用；前端 JS 没有直接读取本地文件或发起带密钥请求的权限。

Android：

- 文件选择器返回的 `content://` URI 通过 Tauri fs plugin 打开，上传链路仍需要真机/模拟器 smoke 覆盖。
- 生命周期监听使用 Tauri `tauri://suspended` / `tauri://resumed` 事件；恢复前台时重新 bootstrap 并恢复 Runtime 订阅。逐 job 主动补齐仍依赖 store 的 SSE 断线 fallback 行为。
- Android 通过生成工程注入的 `SecretPlugin` 使用 Android Keystore + AES-GCM 保存 API Key：密钥在 AndroidKeyStore 中生成且不可导出，加密后的密文存放在 `MODE_PRIVATE` 的 SharedPreferences 中。Android 生成插件已接入并有脚本/Rust 测试覆盖，真实设备仍需 smoke 验证；只有平台安全存储不可用且用户显式确认时，才允许不安全文件降级。

iOS：

- 仅 `keyring` 库的 `apple-native` backend 在代码层兼容 Keychain，未纳入构建/发布（无 iOS 工程/CI/真机路径），不是受支持的发布平台（见 [docs/build.md](../../docs/build.md) “Release 不含 iOS”）。

## 快速开始

```bash
npm install
npm run check
npm run tauri:dev
```

`npm run check` 当前包含 Biome、TypeScript、unit/jsdom integration tests、cargo fmt、cargo check 和 cargo test。

Runtime 默认连接 `http://127.0.0.1:8788`，受保护请求由 Tauri Rust command 注入 `X-Undefined-API-Key`。React 侧不直接持有 API Key。

## Android smoke checklist

桌面检查通过后再运行：

```bash
npm run tauri:android:init
npm run tauri:android:prepare:check
npm run tauri:android:debug -- --apk
```

`tauri:android:init` 会在 Tauri 生成 Android 工程后运行仓库脚本，注入 HTML preview 专用的 `HtmlPreviewActivity` 和 Android Keystore 安全存储用的 `SecretPlugin`。`src-tauri/gen/` 是生成目录，不需要提交。

真机或模拟器至少验证：

- 主界面渲染、移动端会话抽屉、软键盘弹出时输入区和命令面板不被遮挡。
- Runtime LAN 连接、`/health`、发送消息、SSE/JSON fallback。
- 后台运行中 job，回到前台后历史和 active jobs 能恢复。
- 系统相册、Downloads、云盘 provider 返回的 `content://` 文件可以上传。
- HTML 预览 Activity 打开、关闭后不会残留可见窗口或暴露外部导航。
- 安全存储状态；Android 应能保存、重启后读取并删除 API Key。
