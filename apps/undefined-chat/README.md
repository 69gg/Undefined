# Undefined Chat

Undefined Chat 是 `apps/undefined-chat/` 下的 Tauri v2 + React 19 原生聊天客户端。它直接连接 Runtime API；会话、历史、任务、附件和事件以 Runtime 为真源，本地只保存连接配置、API Key 状态、草稿和 UI 游标。

完整产品说明见 [docs/undefined-chat.md](../../docs/undefined-chat.md)。

## 当前能力

- 会话管理：创建、删除、重命名、切换会话。当前没有置顶字段/API。
- 消息历史：初始加载、cursor-based 加载更早消息、滚动锚点保持和长历史窗口化渲染。同一会话的重载与分页共用请求顺序保护；发送新消息、完成任务刷新或删除会话后，迟到的旧响应不会覆盖正文、游标或加载状态。
- 消息渲染：Markdown、表格、任务列表、引用块、代码高亮、代码块复制；未知语言或高亮失败时保留为纯文本代码，代码中的 HTML 不会插入正文。正文 HTML 经 sanitize 内联渲染，HTML 代码块可在独立预览窗口中运行。
- 附件：系统文件选择器、上传状态队列、Tauri 流式上传、下载和预览。当前显示上传中/成功/失败状态，不显示百分比进度。
- 保存连接配置会把尚未完成的附件上传转为失败状态，恢复连接后可移除并重新选择文件；旧上传结果不能恢复已移除条目。同一 Runtime 已上传成功的附件保留，切换 Runtime 清理旧附件。
- 图片：正文 `<attachment uid/>` 内联图、附件缩略图、blob 缓存、全屏查看、缩放、旋转和可滚动查看区域。LRU 目标缓存 60 张；挂载中的图片和已打开的大图持有 blob 引用，超过目标时只淘汰无人使用的项，关闭或卸载消费者后再释放多余缓存。
- 命令：斜杠命令、子命令提示、方向键导航、Tab/Enter 补全；空态反馈（加载中/无匹配/不可用）；窗口聚焦按 TTL 刷新命令列表。
- 引用：引用 bot 消息、划词引用选中文本、发送引用、引用芯片跳转当前已加载源消息；源消息不在当前页时会自动加载一页更早历史，仍未命中需手动继续加载更早历史。
- 工具调用块：层级展示、状态、运行中实时计时、阶段明细（stage detail）、与 WebUI 一致的输入/输出预览（JSON/Python 风格结构化、Markdown 输出、附件图片预览）；历史回放支持 timeline/calls/events 多级回退。
- 自动滚动：智能跟随底部，可在设置面板开关，偏好持久化到 localStorage。
- 重命名只更新目标会话标题，保留当前会话、输入草稿与移动端面板；请求期间切换会话也不会被迟到响应切回。
- 事件：SSE 优先，断开时 JSON fallback（指数退避重连，活跃任务持续重试）；完整任务快照恢复消息与已结束调用，并按快照游标续接，旧 Runtime 的正文前缀也会保留。
- 恢复连接时，已从 active 列表消失的本地任务会补刷所属会话的权威历史，包括非当前会话；仍在历史落盘的终态任务继续保留发送锁，已删除会话不再请求。
- 快捷键：Ctrl/Cmd+N 新会话，Ctrl/Cmd+K 聚焦输入并打开命令模式，Ctrl/Cmd+/ 切换侧栏，Ctrl/Cmd+, 打开设置，Escape 关闭当前弹层/抽屉。
- i18n：中英双语运行时切换，提供语言切换 UI，并按系统语言自动检测默认语言。

## 平台状态

桌面端：

- HTML 渲染对齐 WebUI 基线：正文 HTML 经 sanitize 内联渲染；HTML 代码块在独立预览窗口/Activity 中打开，预览窗口内允许运行脚本，同时保留 `connect-src 'none'`、导航守卫、IPC 隔离、临时 file URL、1 MB 限制和临时文件清理等安全边界。
- API Key 优先保存在系统凭据管理器/Stronghold。macOS 使用 Keychain，Windows 使用系统凭据存储，Linux 依赖 Secret Service；不可用时必须显式确认不安全文件降级。
- Tauri fs/http 插件仅由 Rust commands 内部使用；前端 JS 没有直接读取本地文件或发起带密钥请求的权限。

Android：

- 文件选择器返回的 `content://` URI 通过 Tauri fs plugin 打开，上传链路仍需要真机/模拟器 smoke 覆盖。
- 生命周期监听使用 Tauri `tauri://suspended` / `tauri://resumed` 事件；恢复前台时重新 bootstrap，接受 Runtime 的完整任务时间线与对应游标后恢复订阅；快照内已有事件不会重复追加。
- Android 通过生成工程注入的 `SecretPlugin` 使用 Android Keystore + AES-GCM 保存 API Key：密钥在 AndroidKeyStore 中生成且不可导出，加密后的密文存放在 `MODE_PRIVATE` 的 SharedPreferences 中。Android 生成插件已接入并有脚本/Rust 测试覆盖，真实设备仍需 smoke 验证；只有平台安全存储不可用且用户显式确认时，才允许不安全文件降级。

iOS：

- 仅 `keyring` 库的 `apple-native` backend 在代码层兼容 Keychain，未纳入构建/发布（无 iOS 工程/CI/真机路径），不是受支持的发布平台（见 [docs/build.md](../../docs/build.md) “Release 不含 iOS”）。

## 快速开始

```bash
npm ci
npm run check
npm run tauri:dev
```

`npm run check` 当前包含 Biome、TypeScript、unit/jsdom integration tests、独立 Node production build 回归、cargo fmt、cargo check 和 cargo test。

`npm run build` 将应用、React、其余依赖与代码高亮模块分别打包。highlight.js 的全部语言定义按文件名区间拆成四组，仍同步注册并保留自动检测；分包控制单个 chunk 的体积并细化缓存粒度，全部语言支持保持一致。总下载体积基本不变，独立 gzip 压缩会因减少字典复用而增加压缩体积。`npm run test:build` 在临时目录构建，检查默认 500 kB 限制、chunk 导入图，并执行生产高亮模块，核对完整语言列表、各语言高亮和自动检测结果。

Biome 固定为 **2.5.10**，与 Console 和根目录 WebUI 配置保持一致；使用 `npm ci` 安装锁定版本。App 的 `biome.json` 使用独立嵌套配置（`root: false`），不继承 WebUI 格式规则，并显式启用 React 的 `noArrayIndexKey` 检查，避免依赖自动检测造成漏检；升级约定见 [构建文档](../../docs/build.md#6-git-hook-集成)。

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
