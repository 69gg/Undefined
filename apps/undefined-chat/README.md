# Undefined Chat Phase 0 PoC

Undefined Chat 是独立原生优先 WebChat 客户端的 Phase 0 PoC。当前阶段只验证 Tauri、Runtime 通信、安全存储、事件流、上传和 HTML 预览等高风险路径，不实现完整生产级聊天 UI。

## PoC Verified Paths

- Tauri v2 + React app scaffold。
- Runtime health request through Tauri commands。
- Stronghold/keyring availability probe and API Key round-trip。
- SSE command path for Runtime job events。
- Streaming attachment upload command path。
- Isolated HTML preview with strict CSP。

## Commands

Run from `apps/undefined-chat`:

```bash
npm install
npm run check
npm run tauri:dev
```

## Runtime Requirement

PoC 默认连接 `http://127.0.0.1:8788`。Runtime API 必须配置并接受 `X-Undefined-API-Key`。Runtime health probe 是探测路径；受保护的 Runtime 路径通过 Tauri 命令添加 `X-Undefined-API-Key`。

## Platform Notes

- Linux keyring depends on Secret Service/keyutils availability。
- Android background behavior only after `npm run tauri:android:init` and device testing。
- PoC does not implement full production chat UI。

## Android smoke checklist

Run after desktop PoC checks pass:

```bash
npm run tauri:android:init
npm run tauri:android:debug -- --apk
```

On a device or emulator:

- Open the app and verify the main screen renders.
- Probe secret storage and record whether secure storage is available.
- Connect to Runtime over LAN and verify `/health`.
- Start an SSE stream against a known running job and verify events arrive.
- Upload a file larger than 25 MB and confirm the process does not freeze the UI.
- Open HTML preview and verify it uses the dedicated Android page/window surface.
- Background the app during a running job and record whether events resume after reopening.
