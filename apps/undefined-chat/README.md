# Undefined Chat

Undefined Chat 是独立原生优先 WebChat 客户端，位于 `apps/undefined-chat/`。它直接连接 Runtime API；会话、历史、任务、附件和事件都以 Runtime 为真源，本地只保存连接配置、API Key 状态、草稿和 UI 游标。

完整产品说明见 [docs/undefined-chat.md](../../docs/undefined-chat.md)。

## ✨ 功能特性

Undefined Chat 基于莫兰迪青蓝色系（Morandi Teal-Blue）设计，与 WebUI 保持视觉一致性，100% 移植 WebUI webchat 的所有核心功能，并针对原生平台进行优化。

### P0 核心功能

- ✅ **会话管理**：创建、删除、切换、置顶会话
- ✅ **消息历史分页**：cursor-based 无限滚动加载
- ✅ **Markdown 完整渲染**：表格、引用、列表、任务列表
- ✅ **代码高亮**：highlight.js 支持多语言语法高亮
- ✅ **图片内联展示**：< 12MB 自动内联，> 12MB 预览链接
- ✅ **附件上传/下载**：队列管理、进度显示、流式传输
- ✅ **工具调用块**：层级展示、折叠/展开、执行结果
- ✅ **事件流**：SSE 优先 + JSON polling fallback

### P1 重要功能

- ✅ **命令面板**：斜杠命令自动补全、参数提示
- ✅ **消息引用/回复**：引用芯片、跳转源消息
- ✅ **图片查看器**：全屏查看、缩放、旋转
- ✅ **HTML 预览**：桌面独立窗口 / Android Activity 隔离
- ✅ **代码块折叠**：> 8 行自动折叠，可展开/复制
- ✅ **自动滚动控制**：用户上滑时暂停，下滑恢复
- ✅ **国际化**：中英文界面切换

### 原生平台特性

- 🔐 **安全存储**：API Key 保存在系统凭据管理器（macOS Keychain / Windows Credential Manager / Linux Secret Service）
- ⌨️ **桌面快捷键**：Ctrl/Cmd+K 命令面板、Ctrl/Cmd+N 新会话、Ctrl/Cmd+Enter 发送
- 📱 **Android 生命周期**：后台恢复、连接配置页、原生 Activity
- 🪟 **独立窗口**：HTML 预览使用隔离窗口，严格 CSP 防护

## 核心路径

- Tauri v2 + React app scaffold。
- Runtime health 与受保护 Runtime 请求通过 Tauri commands 发起。
- API Key 使用 Stronghold/keyring 保存，Linux keyring 不可用时需要显式确认降级。
- Runtime job events 以 SSE 优先，必要时回退到 JSON polling。
- 附件通过系统文件选择器进入上传队列，并从 Tauri 文件句柄流式转发。
- HTML preview 使用隔离页面/窗口和严格 CSP；桌面端打开独立窗口，移动端打开独立页面/窗口 surface。

## 🚀 快速开始

在 `apps/undefined-chat` 下运行：

```bash
npm install
npm run check
npm run tauri:dev
```

### Runtime 要求

默认连接 `http://127.0.0.1:8788`。Runtime API 必须启用，并接受 `X-Undefined-API-Key`。React 不直接持有 API Key；受保护路径由 Tauri 命令注入鉴权头。

### 依赖项

- **Tauri v2**：跨平台原生应用框架
- **React 18**：UI 框架
- **TypeScript**：类型安全
- **Vite**：构建工具
- **highlight.js**：代码高亮
- **DOMPurify**：HTML 净化
- **marked**：Markdown 解析
- **Rust**：Tauri 后端（需要 rustc 1.75+）

## 📱 平台支持

### 桌面端（Windows / macOS / Linux）

- ⌨️ 完整快捷键支持（Ctrl/Cmd+K、Ctrl/Cmd+N、Ctrl/Cmd+Enter 等）
- 🪟 HTML 预览使用独立窗口，严格 CSP 隔离
- 🔐 系统凭据管理器安全存储 API Key
- 📋 系统剪贴板集成

### Android

- 📱 原生 Activity 体验
- 🔌 连接配置页，支持 LAN 连接
- 🔄 后台生命周期恢复（恢复前台后自动刷新 active jobs 并补齐事件）
- 🖼️ HTML 预览使用独立 Activity 隔离
- ⚠️ 需要在真实设备或模拟器上验证

### 平台特殊说明

- **Linux keyring**：依赖 Secret Service；不可用时需要用户显式确认后降级到本地存储
- **Release 产物**：使用 `Undefined-Chat-*` 命名，与 `pyproject.toml` 主版本同步

## Android smoke checklist

桌面检查通过后再运行：

```bash
npm run tauri:android:init
npm run tauri:android:prepare:check
npm run tauri:android:debug -- --apk
```

`tauri:android:init` 会在 Tauri 生成 Android 工程后运行仓库脚本，注入 HTML preview 专用的 `HtmlPreviewActivity`。`src-tauri/gen/` 是生成目录，不需要提交。

On a device or emulator:

- Open the app and verify the main screen renders.
- Probe secret storage and record whether secure storage is available.
- Connect to Runtime over LAN and verify `/health`.
- Start an SSE stream against a known running job and verify events arrive.
- Upload a large file and confirm the process does not freeze the UI.
- Open HTML preview and verify it uses the dedicated Android page/window surface.
- Background the app during a running job and record whether events resume after reopening.
