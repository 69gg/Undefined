# Undefined Chat

Undefined Chat 是独立原生优先 WebChat 客户端，位于 `apps/undefined-chat/`。它直接连接 Runtime API；会话、历史、任务、附件和事件都以 Runtime 为真源，本地只保存连接配置、API Key 状态、草稿和 UI 游标。

完整产品说明见 [docs/undefined-chat.md](../../docs/undefined-chat.md)。

## 核心路径

- Tauri v2 + React app scaffold。
- Runtime health 与受保护 Runtime 请求通过 Tauri commands 发起。
- API Key 使用 Stronghold/keyring 保存，Linux keyring 不可用时需要显式确认降级。
- Runtime job events 以 SSE 优先，必要时回退到 JSON polling。
- 附件通过系统文件选择器进入上传队列，并从 Tauri 文件句柄流式转发。
- HTML preview 使用隔离页面/窗口和严格 CSP；桌面端打开独立窗口，移动端打开独立页面/窗口 surface。

## 命令

在 `apps/undefined-chat` 下运行：

```bash
npm install
npm run check
npm run tauri:dev
```

## Runtime 要求

默认连接 `http://127.0.0.1:8788`。Runtime API 必须启用，并接受 `X-Undefined-API-Key`。React 不直接持有 API Key；受保护路径由 Tauri 命令注入鉴权头。

## 平台说明

- Linux keyring 依赖 Secret Service；不可用时只允许用户确认后降级。
- Android 后台行为需要在真实设备或模拟器上验证，恢复前台后应刷新 active jobs 并补齐事件。
- Release 产物使用 `Undefined-Chat-*` 命名，并与 `pyproject.toml` 主版本同步。

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
