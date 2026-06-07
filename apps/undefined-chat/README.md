# Undefined Chat Phase 0 PoC

Undefined Chat 是独立原生优先 WebChat 客户端的 Phase 0 PoC。当前阶段只验证 Tauri、Runtime 通信、安全存储、事件流、上传和 HTML 预览等高风险路径，不实现完整生产级聊天 UI。

## Verified Paths

- Tauri v2 + React app scaffold。
- Runtime health request through Tauri commands。
- Stronghold/keyring availability probe and API Key round-trip。
- SSE command path for Runtime job events。
- Streaming attachment upload command path。
- Isolated HTML preview with strict CSP。

## Commands

```bash
npm install
npm run check
npm run tauri:dev
```

## Runtime Requirement

PoC 默认连接 `http://127.0.0.1:8788`。Runtime API 必须配置并接受 `X-Undefined-API-Key`，客户端通过 Tauri 命令路径添加 API Key 并访问 Runtime。

## Platform Notes

- Linux keyring depends on Secret Service/keyutils availability。
- Android background behavior only after `npm run tauri:android:init` and device testing。
- PoC does not implement full production chat UI。
